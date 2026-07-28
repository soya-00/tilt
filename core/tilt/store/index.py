"""SQLite index — a derived cache, never the record.

Holds a queryable projection of the Markdown tree plus an FTS5 full-text index.
:meth:`Index.rebuild` reconstructs the whole thing from disk, which is the
property that lets the journal outlive the app.

The vector half of hybrid retrieval (``sqlite-vec`` / ``vec0``) attaches here in
a later phase; :mod:`tilt.store.search` already fuses ranked lists so adding a
second ranker is additive rather than a rewrite.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tilt.models import AgentRun, Entry
from tilt.store import files

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    rowid        INTEGER PRIMARY KEY,
    id           TEXT NOT NULL UNIQUE,
    path         TEXT NOT NULL,
    created      TEXT NOT NULL,
    updated      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    provenance   TEXT NOT NULL,
    parent       TEXT,
    source_id    TEXT,
    anchor       TEXT,
    source_url   TEXT,
    reply_kind   TEXT,
    tags         TEXT NOT NULL DEFAULT '[]',
    body         TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_created    ON entries(created DESC);
CREATE INDEX IF NOT EXISTS idx_entries_parent     ON entries(parent);
CREATE INDEX IF NOT EXISTS idx_entries_kind       ON entries(kind);
CREATE INDEX IF NOT EXISTS idx_entries_provenance ON entries(provenance);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    body,
    tags,
    content='entries',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id        TEXT PRIMARY KEY,
    job       TEXT NOT NULL,
    model     TEXT NOT NULL,
    status    TEXT NOT NULL,
    started   TEXT NOT NULL,
    finished  TEXT,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_usd  REAL NOT NULL DEFAULT 0.0,
    error     TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_started ON agent_runs(started DESC);
"""


def content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


class Index:
    """Thin, explicit data-access layer over SQLite.

    Deliberately not an ORM: the schema is small, the queries are hot, and
    keeping SQL visible makes the eventual ``vec0`` join obvious rather than
    hidden behind a query builder.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        with self.tx() as conn:
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- entries

    def upsert(self, entry: Entry, path: Path) -> None:
        payload = (
            entry.id,
            str(path),
            entry.created.isoformat(),
            entry.updated.isoformat(),
            entry.kind.value,
            entry.provenance.value,
            entry.parent,
            entry.source_id,
            entry.anchor,
            entry.source_url,
            entry.reply_kind.value if entry.reply_kind else None,
            json.dumps(entry.tags),
            entry.body,
            content_hash(entry.body),
        )
        with self.tx() as conn:
            existing = conn.execute(
                "SELECT rowid, body, tags FROM entries WHERE id = ?", (entry.id,)
            ).fetchone()
            if existing:
                # FTS5 external-content tables need the old row deleted with its
                # original values before the new one lands, or the index drifts.
                conn.execute(
                    "INSERT INTO entries_fts(entries_fts, rowid, body, tags) "
                    "VALUES ('delete', ?, ?, ?)",
                    (existing["rowid"], existing["body"], existing["tags"]),
                )
                conn.execute(
                    "UPDATE entries SET path=?, created=?, updated=?, kind=?, provenance=?,"
                    " parent=?, source_id=?, anchor=?, source_url=?, reply_kind=?, tags=?,"
                    " body=?, content_hash=? WHERE id=?",
                    (*payload[1:], entry.id),
                )
                rowid = existing["rowid"]
            else:
                cur = conn.execute(
                    "INSERT INTO entries (id, path, created, updated, kind, provenance, parent,"
                    " source_id, anchor, source_url, reply_kind, tags, body, content_hash)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    payload,
                )
                rowid = cur.lastrowid
            conn.execute(
                "INSERT INTO entries_fts(rowid, body, tags) VALUES (?, ?, ?)",
                (rowid, entry.body, json.dumps(entry.tags)),
            )

    def delete(self, entry_id: str) -> bool:
        with self.tx() as conn:
            row = conn.execute(
                "SELECT rowid, body, tags FROM entries WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "INSERT INTO entries_fts(entries_fts, rowid, body, tags) "
                "VALUES ('delete', ?, ?, ?)",
                (row["rowid"], row["body"], row["tags"]),
            )
            conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            return True

    def get(self, entry_id: str) -> Entry | None:
        row = self._conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return _row_to_entry(row) if row else None

    def path_of(self, entry_id: str) -> Path | None:
        row = self._conn.execute("SELECT path FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return Path(row["path"]) if row else None

    def roots(self, *, limit: int = 50, before: str | None = None) -> list[Entry]:
        """Top-level entries, newest first. Replies are fetched per-thread."""
        sql = "SELECT * FROM entries WHERE parent IS NULL"
        args: list[object] = []
        if before:
            sql += " AND created < ?"
            args.append(before)
        sql += " ORDER BY created DESC LIMIT ?"
        args.append(limit)
        return [_row_to_entry(r) for r in self._conn.execute(sql, args)]

    def children(self, parent_ids: list[str]) -> dict[str, list[Entry]]:
        if not parent_ids:
            return {}
        marks = ",".join("?" * len(parent_ids))
        rows = self._conn.execute(
            f"SELECT * FROM entries WHERE parent IN ({marks}) ORDER BY created ASC",
            parent_ids,
        )
        out: dict[str, list[Entry]] = {pid: [] for pid in parent_ids}
        for row in rows:
            out.setdefault(row["parent"], []).append(_row_to_entry(row))
        return out

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM entries").fetchone()["n"]

    def recent_bodies(self, *, limit: int = 20, exclude: str | None = None) -> list[Entry]:
        """Recent self-authored entries — the context an agent call reads from."""
        sql = (
            "SELECT * FROM entries WHERE kind != 'reply' AND provenance = 'self'"
            + (" AND id != ?" if exclude else "")
            + " ORDER BY created DESC LIMIT ?"
        )
        args = [exclude, limit] if exclude else [limit]
        return [_row_to_entry(r) for r in self._conn.execute(sql, args)]

    # ----------------------------------------------------------------- search

    def search_fts(self, query: str, *, limit: int = 20) -> list[tuple[Entry, float]]:
        rows = self._conn.execute(
            "SELECT e.*, bm25(entries_fts) AS score FROM entries_fts"
            " JOIN entries e ON e.rowid = entries_fts.rowid"
            " WHERE entries_fts MATCH ? ORDER BY score LIMIT ?",
            (query, limit),
        )
        return [(_row_to_entry(r), float(r["score"])) for r in rows]

    # ------------------------------------------------------------ agent runs

    def record_run(self, run: AgentRun) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agent_runs (id, job, model, status, started, finished,"
                " tokens_in, tokens_out, cost_usd, error) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run.id,
                    run.job,
                    run.model,
                    run.status,
                    run.started.isoformat(),
                    run.finished.isoformat() if run.finished else None,
                    run.tokens_in,
                    run.tokens_out,
                    run.cost_usd,
                    run.error,
                ),
            )

    def runs(self, *, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM agent_runs ORDER BY started DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    def spend_since(self, iso_ts: str) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total FROM agent_runs WHERE started >= ?",
            (iso_ts,),
        ).fetchone()
        return float(row["total"])

    # ---------------------------------------------------------------- rebuild

    def rebuild(self, entries_root: Path) -> int:
        """Drop the projection and rebuild it from Markdown. The escape hatch."""
        with self.tx() as conn:
            conn.execute("DELETE FROM entries_fts")
            conn.execute("DELETE FROM entries")
        n = 0
        for path in files.walk(entries_root):
            self.upsert(files.parse(path), path)
            n += 1
        return n


def _row_to_entry(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"],
        created=row["created"],
        updated=row["updated"],
        kind=row["kind"],
        provenance=row["provenance"],
        parent=row["parent"],
        source_id=row["source_id"],
        anchor=row["anchor"],
        source_url=row["source_url"],
        reply_kind=row["reply_kind"],
        tags=json.loads(row["tags"]),
        body=row["body"],
    )
