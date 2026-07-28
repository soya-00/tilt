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

from tilt.models import AgentRun, Entry, Link, TagCount, Theme, utcnow
from tilt.store import files

SCHEMA_VERSION = 2


def pair_key(a: str, b: str) -> str:
    """Order-independent identity for a pair of entries."""
    return "|".join(sorted((a, b)))

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

-- Themes are the agent's own categorisation. The user never creates one; they
-- emerge from what has been written and can be renamed, which pins the label.
CREATE TABLE IF NOT EXISTS themes (
    id           TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    created      TEXT NOT NULL,
    updated      TEXT NOT NULL,
    pinned_label INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_themes_label ON themes(label COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS entry_themes (
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    theme_id TEXT NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
    PRIMARY KEY (entry_id, theme_id)
);

CREATE INDEX IF NOT EXISTS idx_entry_themes_theme ON entry_themes(theme_id);

CREATE TABLE IF NOT EXISTS links (
    id        TEXT PRIMARY KEY,
    src_id    TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    dst_id    TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    -- Sorted "a|b" so a pair has one row regardless of which side proposed it.
    -- A dismissal must never come back from the other direction.
    pair_key  TEXT NOT NULL UNIQUE,
    kind      TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    created   TEXT NOT NULL,
    dismissed INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_links_src ON links(src_id);
CREATE INDEX IF NOT EXISTS idx_links_dst ON links(dst_id);

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

    def roots(
        self,
        *,
        limit: int = 50,
        before: str | None = None,
        theme_id: str | None = None,
        tag: str | None = None,
    ) -> list[Entry]:
        """Top-level entries, newest first, optionally scoped to the sidebar
        selection. Replies are fetched per-thread."""
        sql = "SELECT e.* FROM entries e"
        args: list[object] = []
        if theme_id:
            sql += " JOIN entry_themes et ON et.entry_id = e.id AND et.theme_id = ?"
            args.append(theme_id)
        sql += " WHERE e.parent IS NULL"
        if before:
            sql += " AND e.created < ?"
            args.append(before)
        if tag:
            # Tags live in a JSON array; json_each keeps the match exact rather
            # than a LIKE that would let "mind" match "mindfulness".
            sql += (
                " AND EXISTS (SELECT 1 FROM json_each(e.tags)"
                " WHERE json_each.value = ? COLLATE NOCASE)"
            )
            args.append(tag)
        sql += " ORDER BY e.created DESC LIMIT ?"
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

    def count(self, *, authored_only: bool = False) -> int:
        """Total rows, or only what the user actually wrote.

        Machine replies are stored as entries so they are searchable and survive
        in Markdown — but counting them in a user-facing total would report four
        entries to someone who wrote three.
        """
        sql = "SELECT COUNT(*) AS n FROM entries" + (
            " WHERE kind != 'reply'" if authored_only else ""
        )
        return self._conn.execute(sql).fetchone()["n"]

    def recent_bodies(self, *, limit: int = 20, exclude: str | None = None) -> list[Entry]:
        """Recent self-authored entries — the context an agent call reads from."""
        sql = (
            "SELECT * FROM entries WHERE kind != 'reply' AND provenance = 'self'"
            + (" AND id != ?" if exclude else "")
            + " ORDER BY created DESC LIMIT ?"
        )
        args = [exclude, limit] if exclude else [limit]
        return [_row_to_entry(r) for r in self._conn.execute(sql, args)]

    # ----------------------------------------------------------------- themes

    def upsert_theme(self, theme: Theme) -> Theme:
        """Create or update a theme, matching on label case-insensitively.

        Label matching is what stops the agent minting "Attention" alongside an
        existing "attention" every time it categorises.
        """
        with self.tx() as conn:
            row = conn.execute(
                "SELECT * FROM themes WHERE label = ? COLLATE NOCASE", (theme.label,)
            ).fetchone()
            if row:
                # Never overwrite a label the user has pinned by renaming it.
                keep_label = row["label"] if row["pinned_label"] else theme.label
                conn.execute(
                    "UPDATE themes SET label=?, description=?, updated=? WHERE id=?",
                    (
                        keep_label,
                        theme.description or row["description"],
                        theme.updated.isoformat(),
                        row["id"],
                    ),
                )
                return self.get_theme(row["id"])
            conn.execute(
                "INSERT INTO themes (id, label, description, created, updated, pinned_label)"
                " VALUES (?,?,?,?,?,?)",
                (
                    theme.id,
                    theme.label,
                    theme.description,
                    theme.created.isoformat(),
                    theme.updated.isoformat(),
                    int(theme.pinned_label),
                ),
            )
        return self.get_theme(theme.id)

    def get_theme(self, theme_id: str) -> Theme | None:
        row = self._conn.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM entry_themes et WHERE et.theme_id = t.id)"
            " AS count FROM themes t WHERE t.id = ?",
            (theme_id,),
        ).fetchone()
        return _row_to_theme(row) if row else None

    def rename_theme(self, theme_id: str, label: str) -> Theme | None:
        """A user rename pins the label against future agent edits."""
        with self.tx() as conn:
            updated = conn.execute(
                "UPDATE themes SET label=?, pinned_label=1, updated=? WHERE id=?",
                (label, utcnow().isoformat(), theme_id),
            ).rowcount
        return self.get_theme(theme_id) if updated else None

    def themes(self) -> list[Theme]:
        """All themes with membership counts, busiest first."""
        rows = self._conn.execute(
            "SELECT t.*, COUNT(et.entry_id) AS count FROM themes t"
            " LEFT JOIN entry_themes et ON et.theme_id = t.id"
            " GROUP BY t.id ORDER BY count DESC, t.label COLLATE NOCASE ASC"
        )
        return [_row_to_theme(r) for r in rows]

    def set_entry_themes(self, entry_id: str, theme_ids: list[str]) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM entry_themes WHERE entry_id = ?", (entry_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO entry_themes (entry_id, theme_id) VALUES (?, ?)",
                [(entry_id, tid) for tid in theme_ids],
            )

    def themes_for(self, entry_ids: list[str]) -> dict[str, list[Theme]]:
        if not entry_ids:
            return {}
        marks = ",".join("?" * len(entry_ids))
        rows = self._conn.execute(
            f"SELECT et.entry_id, t.*, 0 AS count FROM entry_themes et"
            f" JOIN themes t ON t.id = et.theme_id WHERE et.entry_id IN ({marks})",
            entry_ids,
        )
        out: dict[str, list[Theme]] = {eid: [] for eid in entry_ids}
        for row in rows:
            out.setdefault(row["entry_id"], []).append(_row_to_theme(row))
        return out

    def prune_empty_themes(self) -> int:
        """Themes with no members are noise in the sidebar."""
        with self.tx() as conn:
            return conn.execute(
                "DELETE FROM themes WHERE id NOT IN (SELECT theme_id FROM entry_themes)"
            ).rowcount

    # ------------------------------------------------------------------- tags

    def tags(self) -> list[TagCount]:
        """Tag histogram, derived by unrolling the JSON arrays in Python.

        The corpus is small enough that this is cheaper than maintaining a
        separate tag table, and it keeps Markdown the only place tags live.
        """
        counts: dict[str, int] = {}
        for row in self._conn.execute("SELECT tags FROM entries WHERE kind != 'reply'"):
            for tag in json.loads(row["tags"]):
                counts[tag] = counts.get(tag, 0) + 1
        return [
            TagCount(tag=t, count=c)
            for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    # ------------------------------------------------------------------ links

    def add_link(self, link: Link) -> bool:
        """Record a connection. Returns False when the pair is already judged."""
        with self.tx() as conn:
            try:
                conn.execute(
                    "INSERT INTO links (id, src_id, dst_id, pair_key, kind, rationale,"
                    " created, dismissed) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        link.id,
                        link.src_id,
                        link.dst_id,
                        pair_key(link.src_id, link.dst_id),
                        link.kind.value,
                        link.rationale,
                        link.created.isoformat(),
                        int(link.dismissed),
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def judged_pairs(self, entry_id: str) -> set[str]:
        """Every entry already linked to or dismissed against this one."""
        rows = self._conn.execute(
            "SELECT src_id, dst_id FROM links WHERE src_id = ? OR dst_id = ?",
            (entry_id, entry_id),
        )
        return {r["src_id"] if r["dst_id"] == entry_id else r["dst_id"] for r in rows}

    def links_for(self, entry_ids: list[str]) -> dict[str, list[tuple[Link, Entry]]]:
        """Undirected: a link surfaces on both entries it joins."""
        if not entry_ids:
            return {}
        marks = ",".join("?" * len(entry_ids))
        # Two plain queries rather than one join. A join that picks "the other
        # end" with a CASE returns a single row when BOTH ends are requested,
        # which silently drops the second entry's copy of the link.
        links = [
            _row_to_link(r)
            for r in self._conn.execute(
                f"SELECT * FROM links WHERE dismissed = 0"
                f" AND (src_id IN ({marks}) OR dst_id IN ({marks}))"
                f" ORDER BY created DESC",
                [*entry_ids, *entry_ids],
            )
        ]
        if not links:
            return {eid: [] for eid in entry_ids}

        wanted = set(entry_ids)
        counterparts = {i for link in links for i in (link.src_id, link.dst_id)} - wanted
        counterparts |= {i for link in links for i in (link.src_id, link.dst_id)} & wanted

        others = {e.id: e for e in self._by_ids(sorted(counterparts))}

        out: dict[str, list[tuple[Link, Entry]]] = {eid: [] for eid in entry_ids}
        for link in links:
            for anchor, other_id in ((link.src_id, link.dst_id), (link.dst_id, link.src_id)):
                other = others.get(other_id)
                if anchor in wanted and other is not None:
                    out[anchor].append((link, other))
        return out

    def _by_ids(self, ids: list[str]) -> list[Entry]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return [
            _row_to_entry(r)
            for r in self._conn.execute(f"SELECT * FROM entries WHERE id IN ({marks})", ids)
        ]

    def dismiss_link(self, link_id: str) -> bool:
        """Kept as a tombstone rather than deleted — a dismissal is signal."""
        with self.tx() as conn:
            return (
                conn.execute(
                    "UPDATE links SET dismissed = 1 WHERE id = ?", (link_id,)
                ).rowcount
                > 0
            )

    def all_links(self) -> list[Link]:
        rows = self._conn.execute("SELECT * FROM links WHERE dismissed = 0")
        return [_row_to_link(r) for r in rows]

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


def _row_to_theme(row: sqlite3.Row) -> Theme:
    return Theme(
        id=row["id"],
        label=row["label"],
        description=row["description"],
        created=row["created"],
        updated=row["updated"],
        pinned_label=bool(row["pinned_label"]),
        # `in row` iterates a sqlite3.Row's *values*, not its keys, so the
        # .keys() call is load-bearing here rather than redundant.
        count=row["count"] if "count" in row.keys() else 0,  # noqa: SIM118
    )


def _row_to_link(row: sqlite3.Row) -> Link:
    return Link(
        id=row["id"],
        src_id=row["src_id"],
        dst_id=row["dst_id"],
        kind=row["kind"],
        rationale=row["rationale"],
        created=row["created"],
        dismissed=bool(row["dismissed"]),
    )


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
