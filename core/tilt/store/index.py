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
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from tilt.folders import Decisions
from tilt.models import (
    AgentRun,
    Conflict,
    Entry,
    Link,
    Misfiled,
    Notice,
    TagCount,
    Theme,
    ThemeSplit,
    ThemeStatus,
    utcnow,
)
from tilt.store import files

log = logging.getLogger(__name__)

SCHEMA_VERSION = 6


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
    -- Whether an extracted idea earned a place in the Stream. Only cards are
    -- ever demoted; everything you wrote yourself is promoted by definition.
    promoted     INTEGER NOT NULL DEFAULT 1,
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
    pinned_label INTEGER NOT NULL DEFAULT 0,
    -- 'active' | 'dormant'. Set by the nightly keeper from when the theme last
    -- gained a member; never a reason to hide it, only to render it quietly.
    status       TEXT NOT NULL DEFAULT 'active'
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
    error     TEXT,
    detail    TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_started ON agent_runs(started DESC);

-- What the agent has already considered.
--
-- Without this an entry the connector correctly found nothing for is
-- indistinguishable from one it never looked at, so the nightly sweep would
-- re-judge every unconnected thought forever. Index-only state: losing it to a
-- rebuild costs one redundant pass, which is why it is not in the Markdown.
CREATE TABLE IF NOT EXISTS entry_state (
    entry_id  TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    filed_at  TEXT,
    judged_at TEXT
);

-- A folder the keeper thinks has become two subjects. Never applied on its own:
-- a wrong merge is visible and reversible, a wrong split scatters a subject and
-- nothing looks at the halves together again.
--
-- One row per theme. A dismissal keeps its row rather than deleting it, with
-- the folder's size at the time, so "no" holds until the subject has actually
-- changed instead of until tomorrow night.
CREATE TABLE IF NOT EXISTS theme_splits (
    id          TEXT PRIMARY KEY,
    theme_id    TEXT NOT NULL UNIQUE REFERENCES themes(id) ON DELETE CASCADE,
    keep_label  TEXT NOT NULL,
    move_label  TEXT NOT NULL,
    keep_ids    TEXT NOT NULL DEFAULT '[]',
    move_ids    TEXT NOT NULL DEFAULT '[]',
    separation  REAL NOT NULL DEFAULT 0.0,
    created     TEXT NOT NULL,
    -- 'pending' | 'dismissed'. Accepting deletes the row: the folders are the
    -- record of that decision, and a kept row would propose a split already made.
    state       TEXT NOT NULL DEFAULT 'pending',
    size_at_decision INTEGER NOT NULL DEFAULT 0
);

-- An entry the filing pass thinks is in the wrong folder. Offered, never
-- applied: one row per entry, replaced when a later pass measures it again.
CREATE TABLE IF NOT EXISTS entry_moves (
    id        TEXT PRIMARY KEY,
    entry_id  TEXT NOT NULL UNIQUE REFERENCES entries(id) ON DELETE CASCADE,
    opening   TEXT NOT NULL DEFAULT '',
    from_id   TEXT NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
    from_label TEXT NOT NULL,
    to_id     TEXT NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
    to_label  TEXT NOT NULL,
    margin    REAL NOT NULL DEFAULT 0.0,
    created   TEXT NOT NULL
);

-- What the weekly pass noticed. Usually nothing, which is the point.
CREATE TABLE IF NOT EXISTS notices (
    id        TEXT PRIMARY KEY,
    kind      TEXT NOT NULL,
    body      TEXT NOT NULL,
    entry_ids TEXT NOT NULL DEFAULT '[]',
    -- The link or question the notice is about, so the same finding cannot be
    -- raised again next week when it is still just as true.
    subject   TEXT NOT NULL UNIQUE,
    created   TEXT NOT NULL,
    dismissed INTEGER NOT NULL DEFAULT 0
);
"""

_ADDED_COLUMNS = (
    ("themes", "status", "TEXT NOT NULL DEFAULT 'active'"),
    ("agent_runs", "detail", "TEXT NOT NULL DEFAULT ''"),
    # Defaults to 1 so every card in a journal that predates the promotion bar
    # keeps showing exactly where it already shows. Nothing vanishes on upgrade.
    ("entries", "promoted", "INTEGER NOT NULL DEFAULT 1"),
)


_THEME_STATS = """
    (SELECT COUNT(*) FROM entry_themes et WHERE et.theme_id = t.id) AS count,
    (SELECT MAX(e.created) FROM entry_themes et JOIN entries e ON e.id = et.entry_id
     WHERE et.theme_id = t.id) AS last_active
"""
"""Membership size and freshness, derived per theme rather than cached.

Correlated subqueries instead of a GROUP BY join: the join form multiplies rows
before aggregating, so counting and taking a maximum in the same query needs
either two passes or a subquery anyway.
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
        # Filled by `rebuild`, the only thing that can see two files claiming
        # one id. Empty on a healthy journal, which is almost always.
        self.conflicts: list[Conflict] = []
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        with self.tx() as conn:
            conn.executescript(_SCHEMA)
            # `CREATE TABLE IF NOT EXISTS` is a no-op on a table that already
            # exists, so a column added to the schema above never reaches an
            # index built by an earlier version. Dropping and rebuilding would
            # be simpler but would discard every theme name the user has pinned,
            # which lives nowhere else.
            for table, column, decl in _ADDED_COLUMNS:
                present = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                if column not in present:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
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
            int(entry.promoted),
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
                    " promoted=?, body=?, content_hash=? WHERE id=?",
                    (*payload[1:], entry.id),
                )
                rowid = existing["rowid"]
            else:
                cur = conn.execute(
                    "INSERT INTO entries (id, path, created, updated, kind, provenance, parent,"
                    " source_id, anchor, source_url, reply_kind, tags, promoted, body,"
                    " content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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

    def open_questions(self, *, limit: int = 12) -> list[Entry]:
        """What sources left unresolved, newest first.

        Distillation already extracts these and stores them as cards, so the
        journal knows what you have been left wondering about without anyone
        being asked to keep a list. They are the sharpest thing to go looking
        on behalf of: a subject is a topic, a question is a gap.
        """
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE kind = 'card' AND reply_kind = 'question'"
            " ORDER BY created DESC LIMIT ?",
            (limit,),
        )
        return [_row_to_entry(r) for r in rows]

    def known_urls(self) -> set[str]:
        """Every source URL the journal already holds.

        Half of the scout's memory. The other half is the brief's tombstones;
        between them, nothing already read or already refused comes back.
        """
        rows = self._conn.execute(
            "SELECT source_url FROM entries WHERE source_url IS NOT NULL AND source_url != ''"
        )
        return {str(r["source_url"]) for r in rows}

    def all_entries(self) -> list[Entry]:
        """Every entry, oldest first.

        For the passes that must consider the whole journal rather than a page
        of it. Replies are included: a reflection is text the writer may search
        for and may want found, even though it is not drawn in the graph.
        """
        rows = self._conn.execute("SELECT * FROM entries ORDER BY created")
        return [_row_to_entry(r) for r in rows]

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
                # Filing something new into a dormant theme is exactly what it
                # means for the subject to have come back.
                conn.execute(
                    "UPDATE themes SET label=?, description=?, updated=?, status='active'"
                    " WHERE id=?",
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
            f"SELECT t.*, {_THEME_STATS} FROM themes t WHERE t.id = ?", (theme_id,)
        ).fetchone()
        return _row_to_theme(row) if row else None

    def pin_theme(self, theme_id: str) -> None:
        """Mark a name as the user's without changing it.

        Renaming already pins; this is the other half, for replaying a pin that
        was recorded in `folders.md` onto a freshly rebuilt index. The name is
        already right — what was lost was the fact that it is yours.
        """
        with self.tx() as conn:
            conn.execute("UPDATE themes SET pinned_label=1 WHERE id=?", (theme_id,))

    def record_declined_split(self, theme_id: str, *, at: int) -> None:
        """Restore a refusal that has no proposal behind it any more.

        The proposal was a row in a database somebody deleted; the refusal is a
        decision they made. Written back as a dismissed row so every gate that
        reads `theme_splits` keeps working unchanged.
        """
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO theme_splits (id, theme_id, keep_label, move_label,"
                " separation, created, state, size_at_decision)"
                " VALUES (?,?,'','',0,?, 'dismissed', ?)"
                " ON CONFLICT(theme_id) DO UPDATE SET"
                "  state='dismissed', size_at_decision=excluded.size_at_decision",
                (files.new_id(), theme_id, utcnow().isoformat(), at),
            )

    def rename_theme(self, theme_id: str, label: str) -> Theme | None:
        """A user rename pins the label against future agent edits."""
        with self.tx() as conn:
            updated = conn.execute(
                "UPDATE themes SET label=?, pinned_label=1, updated=? WHERE id=?",
                (label, utcnow().isoformat(), theme_id),
            ).rowcount
        return self.get_theme(theme_id) if updated else None

    def delete_theme(self, theme_id: str) -> bool:
        """Remove a theme and every entry's membership of it.

        ``entry_themes`` cascades on the foreign key, so the memberships go with
        the row and the entries themselves are never touched. Callers are
        responsible for rewriting the affected entries' frontmatter afterwards —
        Markdown is the durable copy, and a delete that touched only SQLite
        would bring the folder straight back on the next rebuild.
        """
        with self.tx() as conn:
            return conn.execute("DELETE FROM themes WHERE id = ?", (theme_id,)).rowcount > 0

    def themes(self) -> list[Theme]:
        """All themes with membership counts. Live ones first, then busiest.

        Dormant themes sort last rather than being filtered out — what you have
        stopped thinking about is part of the shape of how you think.
        """
        rows = self._conn.execute(
            f"SELECT t.*, {_THEME_STATS} FROM themes t"
            " ORDER BY (t.status = 'dormant'), count DESC, t.label COLLATE NOCASE ASC"
        )
        return [_row_to_theme(r) for r in rows]

    def set_theme_status(self, theme_id: str, status: ThemeStatus) -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE themes SET status = ? WHERE id = ?", (status.value, theme_id)
            )

    def merge_themes(self, keep_id: str, drop_id: str) -> int:
        """Fold one theme into another. Returns how many entries moved.

        The losing theme's members are re-pointed rather than copied, so an
        entry never ends up in both halves of a merge. Callers are responsible
        for rewriting the affected entries' frontmatter afterwards — SQLite is
        the projection here, and leaving the Markdown stale would resurrect the
        dead theme on the next rebuild.
        """
        if keep_id == drop_id:
            return 0
        with self.tx() as conn:
            moved = [
                r["entry_id"]
                for r in conn.execute(
                    "SELECT entry_id FROM entry_themes WHERE theme_id = ?", (drop_id,)
                )
            ]
            conn.executemany(
                "INSERT OR IGNORE INTO entry_themes (entry_id, theme_id) VALUES (?, ?)",
                [(eid, keep_id) for eid in moved],
            )
            conn.execute("DELETE FROM themes WHERE id = ?", (drop_id,))
        return len(moved)

    def entries_in_theme(self, theme_id: str) -> list[Entry]:
        rows = self._conn.execute(
            "SELECT e.* FROM entries e JOIN entry_themes et ON et.entry_id = e.id"
            " WHERE et.theme_id = ? ORDER BY e.created DESC",
            (theme_id,),
        )
        return [_row_to_entry(r) for r in rows]

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

    # --------------------------------------------------------- split proposals

    def propose_split(self, split: ThemeSplit, *, members: int) -> ThemeSplit:
        """Record a split for the writer to decide on. Never applies anything.

        Replaces any pending proposal for the same folder — the newer reading of
        it is the better one, and two proposals for one folder is a question
        nobody asked to be asked twice.
        """
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO theme_splits (id, theme_id, keep_label, move_label,"
                " keep_ids, move_ids, separation, created, state, size_at_decision)"
                " VALUES (?,?,?,?,?,?,?,?,'pending',?)"
                " ON CONFLICT(theme_id) DO UPDATE SET"
                "  id=excluded.id, keep_label=excluded.keep_label,"
                "  move_label=excluded.move_label, keep_ids=excluded.keep_ids,"
                "  move_ids=excluded.move_ids, separation=excluded.separation,"
                "  created=excluded.created, state='pending',"
                "  size_at_decision=excluded.size_at_decision",
                (
                    split.id,
                    split.theme_id,
                    split.keep_label,
                    split.move_label,
                    json.dumps(split.keep_ids),
                    json.dumps(split.move_ids),
                    split.separation,
                    split.created.isoformat(),
                    members,
                ),
            )
        return split

    def pending_splits(self) -> list[ThemeSplit]:
        rows = self._conn.execute(
            "SELECT s.*, t.label AS theme_label FROM theme_splits s"
            " JOIN themes t ON t.id = s.theme_id"
            " WHERE s.state = 'pending' ORDER BY s.separation DESC"
        )
        return [_row_to_split(r) for r in rows]

    def get_split(self, split_id: str) -> ThemeSplit | None:
        row = self._conn.execute(
            "SELECT s.*, t.label AS theme_label FROM theme_splits s"
            " JOIN themes t ON t.id = s.theme_id WHERE s.id = ?",
            (split_id,),
        ).fetchone()
        return _row_to_split(row) if row else None

    def dismiss_split(self, split_id: str) -> bool:
        """Turn a proposal down, and remember the folder's size at the time.

        Kept rather than deleted, exactly like a dismissed connection: without
        the tombstone the same folder is proposed again tomorrow night, and a
        suggestion that ignores your answer is worse than one you never saw.
        """
        with self.tx() as conn:
            return (
                conn.execute(
                    "UPDATE theme_splits SET state='dismissed',"
                    " size_at_decision=(SELECT COUNT(*) FROM entry_themes"
                    "  WHERE theme_id = theme_splits.theme_id)"
                    " WHERE id = ? AND state = 'pending'",
                    (split_id,),
                ).rowcount
                > 0
            )

    def clear_split(self, theme_id: str) -> None:
        """Forget a folder's proposal outright. For when it has been applied —
        the two folders are now the record of that decision."""
        with self.tx() as conn:
            conn.execute("DELETE FROM theme_splits WHERE theme_id = ?", (theme_id,))

    def split_settled(self, theme_id: str, *, members: int, growth: float) -> bool:
        """Whether this folder has already been ruled on and has not changed since.

        A dismissal holds until the folder has grown by ``growth`` — a folder
        that has gained half again as many entries is arguably a different
        folder, and asking once more about it is not nagging. Anything less is.
        """
        row = self._conn.execute(
            "SELECT state, size_at_decision FROM theme_splits WHERE theme_id = ?",
            (theme_id,),
        ).fetchone()
        if row is None:
            return False
        if row["state"] == "pending":
            return True
        return members < row["size_at_decision"] * growth

    # ------------------------------------------------------------- refiling

    def propose_move(self, move: Misfiled, *, declined: Decisions | None = None) -> bool:
        """Offer to refile one entry, unless the writer already said no.

        The refusal is checked here rather than in the pass so that every path
        into this table goes through it — a proposal that reappears after being
        turned down is the failure this whole shape of feature has to avoid.
        """
        if declined is not None and declined.refused_move(move.entry_id, move.to_label):
            return False
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO entry_moves (id, entry_id, opening, from_id, from_label,"
                " to_id, to_label, margin, created) VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(entry_id) DO UPDATE SET"
                "  id=excluded.id, opening=excluded.opening, from_id=excluded.from_id,"
                "  from_label=excluded.from_label, to_id=excluded.to_id,"
                "  to_label=excluded.to_label, margin=excluded.margin,"
                "  created=excluded.created",
                (
                    move.id,
                    move.entry_id,
                    move.opening,
                    move.from_id,
                    move.from_label,
                    move.to_id,
                    move.to_label,
                    move.margin,
                    move.created.isoformat(),
                ),
            )
        return True

    def pending_moves(self) -> list[Misfiled]:
        rows = self._conn.execute("SELECT * FROM entry_moves ORDER BY margin DESC")
        return [_row_to_move(r) for r in rows]

    def get_move(self, move_id: str) -> Misfiled | None:
        row = self._conn.execute(
            "SELECT * FROM entry_moves WHERE id = ?", (move_id,)
        ).fetchone()
        return _row_to_move(row) if row else None

    def clear_move(self, entry_id: str) -> None:
        """Forget a proposal, whether it was taken or turned down. The durable
        record of a refusal is in `folders.md`; this table is the projection."""
        with self.tx() as conn:
            conn.execute("DELETE FROM entry_moves WHERE entry_id = ?", (entry_id,))

    # ------------------------------------------------------------------ notices

    def add_notice(self, notice: Notice) -> bool:
        """Raise a notice, unless this exact finding has been raised before.

        Returns whether it was new. The weekly pass would otherwise report the
        same contradiction every Sunday for as long as it remains true, which is
        forever.
        """
        with self.tx() as conn:
            return (
                conn.execute(
                    "INSERT INTO notices (id, kind, body, entry_ids, subject, created,"
                    " dismissed) VALUES (?,?,?,?,?,?,0)"
                    " ON CONFLICT(subject) DO NOTHING",
                    (
                        notice.id,
                        notice.kind,
                        notice.body,
                        json.dumps(notice.entry_ids),
                        notice.subject,
                        notice.created.isoformat(),
                    ),
                ).rowcount
                > 0
            )

    def open_notices(self) -> list[Notice]:
        rows = self._conn.execute(
            "SELECT * FROM notices WHERE dismissed = 0 ORDER BY created DESC"
        )
        return [_row_to_notice(r) for r in rows]

    def get_notice(self, notice_id: str) -> Notice | None:
        row = self._conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
        return _row_to_notice(row) if row else None

    def dismiss_notice(self, notice_id: str) -> bool:
        with self.tx() as conn:
            return (
                conn.execute(
                    "UPDATE notices SET dismissed = 1 WHERE id = ? AND dismissed = 0",
                    (notice_id,),
                ).rowcount
                > 0
            )

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

    # ------------------------------------------------------------ agent state

    def mark_considered(self, entry_id: str, *, filed: bool = False, judged: bool = False) -> None:
        """Record that an agent has looked at this entry.

        Written by the agents themselves rather than by the sweep, so work the
        UI did in the foreground is not repeated in the background an hour
        later.
        """
        now = utcnow().isoformat()
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO entry_state (entry_id, filed_at, judged_at) VALUES (?, ?, ?)"
                " ON CONFLICT(entry_id) DO UPDATE SET"
                "   filed_at  = COALESCE(excluded.filed_at,  filed_at),"
                "   judged_at = COALESCE(excluded.judged_at, judged_at)",
                (entry_id, now if filed else None, now if judged else None),
            )

    def _restore_considered(
        self, entry_id: str, *, filed: datetime | None, judged: datetime | None
    ) -> None:
        """Replay the marks recorded in an entry's frontmatter.

        Separate from :meth:`mark_considered` because that one stamps *now*,
        which is right when an agent has just finished and wrong when a rebuild
        is recovering something that happened last March.
        """
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO entry_state (entry_id, filed_at, judged_at) VALUES (?, ?, ?)"
                " ON CONFLICT(entry_id) DO UPDATE SET"
                "   filed_at  = COALESCE(filed_at,  excluded.filed_at),"
                "   judged_at = COALESCE(judged_at, excluded.judged_at)",
                (
                    entry_id,
                    filed.isoformat() if filed else None,
                    judged.isoformat() if judged else None,
                ),
            )

    def backlog(self, *, limit: int, settled_before: str) -> list[tuple[Entry, bool, bool]]:
        """Entries no agent has finished with, newest first.

        ``settled_before`` excludes anything written in the last few minutes.
        The interface already files an entry the moment you keep it, and without
        a quiet period the sweep would race that request and pay for the same
        judgement twice.

        Cards are the one kind of child that qualifies. An idea pulled out of
        something you read is exactly what should meet a thought you had in
        March — that meeting is the whole reason to ingest anything. Replies and
        every other child stay out.

        Returns each entry with whether it still needs filing and judging.
        """
        rows = self._conn.execute(
            "SELECT e.*, s.filed_at, s.judged_at FROM entries e"
            " LEFT JOIN entry_state s ON s.entry_id = e.id"
            " WHERE (e.parent IS NULL OR e.kind = 'card') AND e.kind != 'reply'"
            "   AND e.created < ?"
            "   AND (s.filed_at IS NULL OR s.judged_at IS NULL)"
            " ORDER BY e.created DESC LIMIT ?",
            (settled_before, limit),
        )
        return [
            (_row_to_entry(r), r["filed_at"] is None, r["judged_at"] is None) for r in rows
        ]

    def filed_since(self, iso_ts: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM entry_state WHERE filed_at >= ?", (iso_ts,)
        ).fetchone()
        return int(row["n"])

    def links_since(self, iso_ts: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM links WHERE dismissed = 0 AND created >= ?", (iso_ts,)
        ).fetchone()
        return int(row["n"])

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

    def get_link(self, link_id: str) -> Link | None:
        row = self._conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
        return _row_to_link(row) if row else None

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

    def links_of_kind(self, kind: str, *, since: str) -> list[Link]:
        """Connections of one kind made recently, newest first.

        For the weekly pass, which cares about one kind in particular: a
        contradiction is the only link the connector will only ever draw between
        two things the writer wrote themselves.
        """
        rows = self._conn.execute(
            "SELECT * FROM links WHERE kind = ? AND dismissed = 0 AND created >= ?"
            " ORDER BY created DESC",
            (kind, since),
        )
        return [_row_to_link(r) for r in rows]

    def written_since(self, iso_ts: str) -> list[Entry]:
        """What the writer wrote in a window — not what the machine replied."""
        rows = self._conn.execute(
            "SELECT * FROM entries WHERE kind != 'reply' AND created >= ?"
            " ORDER BY created DESC",
            (iso_ts,),
        )
        return [_row_to_entry(r) for r in rows]

    def all_links(self) -> list[Link]:
        rows = self._conn.execute("SELECT * FROM links WHERE dismissed = 0")
        return [_row_to_link(r) for r in rows]

    # ------------------------------------------------------------------ graph

    @staticmethod
    def _graph_where(
        since: str | None, theme_id: str | None, include_sources: bool
    ) -> tuple[str, list[object]]:
        """The filter shared by the graph query and its count.

        Written once because the two must agree: a count derived from different
        predicates than the rows would let the view say "showing 300 of 412"
        when 412 was never drawable in the first place.
        """
        clauses = ["e.kind != 'reply'", "e.promoted = 1"]
        args: list[object] = []
        if not include_sources:
            clauses.append("e.provenance = 'self'")
        if since:
            clauses.append("e.created >= ?")
            args.append(since)
        if theme_id:
            clauses.append(
                "EXISTS (SELECT 1 FROM entry_themes et"
                " WHERE et.entry_id = e.id AND et.theme_id = ?)"
            )
            args.append(theme_id)
        return " AND ".join(clauses), args

    def graph_entries(
        self,
        *,
        limit: int,
        since: str | None = None,
        theme_id: str | None = None,
        include_sources: bool = False,
    ) -> list[Entry]:
        """The entries a constellation should draw, newest first.

        Replies are never nodes: a reflection is something the app said about a
        thought, not a second thought, and drawing both doubles the graph
        without adding anything to look at.

        Sources are off by default. An unfiltered graph is a hairball, and the
        first thing worth seeing is your own thinking — borrowed material is a
        toggle rather than the default.
        """
        where, args = self._graph_where(since, theme_id, include_sources)
        # Ordered by how connected an entry is, not by how recent it is. The cap
        # only bites on a large journal, and that is exactly where newest-first
        # is wrong: the view drops every hub older than the last few hundred
        # entries and draws the sparsest possible picture of a dense journal.
        # Ties fall back to recency, so a journal with no links yet still reads
        # newest-first.
        rows = self._conn.execute(
            f"""
            WITH degree AS (
                SELECT id, SUM(n) AS n FROM (
                    SELECT src_id AS id, COUNT(*) AS n FROM links
                     WHERE dismissed = 0 GROUP BY src_id
                    UNION ALL
                    SELECT dst_id AS id, COUNT(*) AS n FROM links
                     WHERE dismissed = 0 GROUP BY dst_id
                ) GROUP BY id
            )
            SELECT e.* FROM entries e
            LEFT JOIN degree d ON d.id = e.id
            WHERE {where}
            ORDER BY COALESCE(d.n, 0) DESC, e.created DESC
            LIMIT ?
            """,
            [*args, limit],
        )
        return [_row_to_entry(r) for r in rows]

    def graph_count(
        self,
        *,
        since: str | None = None,
        theme_id: str | None = None,
        include_sources: bool = False,
    ) -> int:
        """How many entries the same filter would match, uncapped."""
        where, args = self._graph_where(since, theme_id, include_sources)
        row = self._conn.execute(
            f"SELECT COUNT(*) AS n FROM entries e WHERE {where}", args
        ).fetchone()
        return int(row["n"]) if row else 0

    def links_between(self, entry_ids: list[str]) -> list[Link]:
        """Links with both ends inside the given set.

        Both ends, not either: an edge to a node that was filtered out has
        nothing to attach to, and force layouts either drop it or invent a
        phantom node for it.
        """
        if not entry_ids:
            return []
        marks = ",".join("?" * len(entry_ids))
        rows = self._conn.execute(
            f"SELECT * FROM links WHERE dismissed = 0"
            f" AND src_id IN ({marks}) AND dst_id IN ({marks})",
            [*entry_ids, *entry_ids],
        )
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
                " tokens_in, tokens_out, cost_usd, error, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
                    run.detail,
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
        """Reconcile the projection against Markdown on disk.

        Deliberately a reconcile, not a drop-and-reload. ``entry_themes`` and
        ``links`` cascade from ``entries``, so deleting every row would destroy
        the agent's folder assignments and connections on every boot. Instead we
        upsert what is on disk and delete only what has vanished from it.

        Themes and links are then restored from each entry's own frontmatter, so
        a genuinely empty index still comes back whole.

        Two files can claim one id — a sync client's "(conflicted copy)" carries
        the id of the file it copied. Those are recorded in :attr:`conflicts`
        and reported rather than resolved: the newer one is indexed, because
        picking by ``updated`` is at least a reason where sorted-path order is
        an accident, and both paths are named so it can be settled by hand.
        Renaming or merging somebody's files without asking is not this
        function's business.
        """
        self.conflicts = []
        claimed: dict[str, tuple[Entry, Path]] = {}
        for path in files.walk(entries_root):
            entry = files.parse(path)
            held = claimed.get(entry.id)

            if held is None:
                claimed[entry.id] = (entry, path)
                continue

            held_entry, held_path = held
            newer = (entry, path) if entry.updated > held_entry.updated else held
            older = held if newer[1] is path else (entry, path)
            claimed[entry.id] = newer

            self.conflicts.append(
                Conflict(entry_id=entry.id, kept=str(newer[1]), ignored=str(older[1]))
            )
            log.warning(
                "two files claim entry %s: keeping %s, ignoring %s",
                entry.id,
                newer[1].name,
                older[1].name,
            )

        parsed: list[tuple[Entry, Path]] = list(claimed.values())
        for entry, path in parsed:
            self.upsert(entry, path)

        on_disk = {entry.id for entry, _ in parsed}
        stale = [
            row["id"]
            for row in self._conn.execute("SELECT id FROM entries")
            if row["id"] not in on_disk
        ]
        for entry_id in stale:
            self.delete(entry_id)

        self._restore_structure(parsed)
        return len(parsed)

    def _restore_structure(self, parsed: list[tuple[Entry, Path]]) -> None:
        """Re-derive themes, links, and what has already been considered.

        Only fills gaps: an entry whose membership is already present is left
        alone, so this is safe to run on every boot.
        """
        by_label: dict[str, str] = {t.label.lower(): t.id for t in self.themes()}

        for entry, _ in parsed:
            # Without this a journal rebuilt from a deleted index would look
            # entirely unexamined, and the next sweep would re-file and
            # re-judge every thought in it at full price — for answers already
            # sitting on disk. Timestamps are carried over rather than
            # regenerated, so a rebuild does not pretend the work happened now.
            if entry.filed or entry.judged:
                self._restore_considered(entry.id, filed=entry.filed, judged=entry.judged)

            if entry.theme_labels:
                theme_ids: list[str] = []
                for label in entry.theme_labels:
                    theme_id = by_label.get(label.lower())
                    if theme_id is None:
                        now = utcnow()
                        theme = self.upsert_theme(
                            Theme(id=files.new_id(), label=label, created=now, updated=now)
                        )
                        theme_id = theme.id
                        by_label[label.lower()] = theme_id
                    theme_ids.append(theme_id)
                self.set_entry_themes(entry.id, theme_ids)

            for record in entry.links:
                try:
                    link = Link(
                        id=files.new_id(),
                        src_id=entry.id,
                        dst_id=record.to,
                        kind=record.kind,
                        rationale=record.why,
                        created=entry.updated,
                        dismissed=record.dismissed,
                    )
                except ValidationError:
                    continue  # hand-edited frontmatter; skip, never crash
                self.add_link(link)


def _row_to_theme(row: sqlite3.Row) -> Theme:
    # `in row` iterates a sqlite3.Row's *values*, not its keys, so the .keys()
    # call is load-bearing here rather than redundant.
    columns = row.keys()
    return Theme(
        id=row["id"],
        label=row["label"],
        description=row["description"],
        created=row["created"],
        updated=row["updated"],
        pinned_label=bool(row["pinned_label"]),
        status=row["status"],
        count=row["count"] if "count" in columns else 0,
        last_active=row["last_active"] if "last_active" in columns else None,
    )


def _row_to_split(row: sqlite3.Row) -> ThemeSplit:
    # Bound first for the same reason as in `_row_to_theme`: `in row` iterates a
    # sqlite3.Row's values rather than its column names.
    columns = row.keys()
    return ThemeSplit(
        id=row["id"],
        theme_id=row["theme_id"],
        theme_label=row["theme_label"] if "theme_label" in columns else "",
        keep_label=row["keep_label"],
        move_label=row["move_label"],
        keep_ids=json.loads(row["keep_ids"]),
        move_ids=json.loads(row["move_ids"]),
        separation=row["separation"],
        created=row["created"],
    )


def _row_to_move(row: sqlite3.Row) -> Misfiled:
    return Misfiled(
        id=row["id"],
        entry_id=row["entry_id"],
        opening=row["opening"],
        from_id=row["from_id"],
        from_label=row["from_label"],
        to_id=row["to_id"],
        to_label=row["to_label"],
        margin=row["margin"],
        created=row["created"],
    )


def _row_to_notice(row: sqlite3.Row) -> Notice:
    return Notice(
        id=row["id"],
        kind=row["kind"],
        body=row["body"],
        entry_ids=json.loads(row["entry_ids"]),
        subject=row["subject"],
        created=row["created"],
        dismissed=bool(row["dismissed"]),
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
        promoted=bool(row["promoted"]),
        body=row["body"],
    )
