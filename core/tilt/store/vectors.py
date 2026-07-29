"""Vectors — a cache with a price, kept apart from the one without.

``index.db`` is disposable. The README says so, the rebuild path proves it, and
several tests exist only to keep it true: delete it and everything comes back
from Markdown for free.

Vectors are not. Every one of them was bought from a hosted model, and
recomputing the set is a bill. Putting them in ``index.db`` would attach that
bill to an operation the app advertises as costless — and eventually someone
deletes the index to fix an unrelated problem and pays for their whole journal
without being told. So they live in their own file, and the two can be thrown
away independently: one is free to rebuild, the other is merely *possible* to.

That is the entire reason this module exists rather than three more columns on
``entries``.
"""

from __future__ import annotations

import sqlite3
from array import array
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
    entry_id     TEXT NOT NULL,
    signature    TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    dims         INTEGER NOT NULL,
    vector       BLOB NOT NULL,
    PRIMARY KEY (entry_id, signature)
);

CREATE INDEX IF NOT EXISTS idx_vectors_signature ON vectors(signature);
"""


def pack(vector: list[float]) -> bytes:
    """Float32 rather than float64: half the file, and the extra precision is
    meaningless against embeddings that are themselves approximations."""
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> list[float]:
    out = array("f")
    out.frombytes(blob)
    return out.tolist()


class VectorStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- writing

    def put(self, entry_id: str, signature: str, content_hash: str, vector: list[float]) -> None:
        self._conn.execute(
            "INSERT INTO vectors (entry_id, signature, content_hash, dims, vector)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(entry_id, signature) DO UPDATE SET"
            " content_hash=excluded.content_hash, dims=excluded.dims,"
            " vector=excluded.vector",
            (entry_id, signature, content_hash, len(vector), pack(vector)),
        )
        self._conn.commit()

    def forget(self, entry_id: str) -> None:
        """Drop every vector for an entry, whatever embedded it.

        Called when the entry is deleted, so the store does not accumulate
        vectors for thoughts that no longer exist.
        """
        self._conn.execute("DELETE FROM vectors WHERE entry_id = ?", (entry_id,))
        self._conn.commit()

    def drop_signature(self, signature: str) -> int:
        """Discard every vector from one embedder.

        For when the configured model changes. Vectors from two models are not
        comparable — cosine between them is a number with no meaning — and
        keeping the old rows would return neighbours that are simply noise.
        """
        with self._conn:
            return self._conn.execute(
                "DELETE FROM vectors WHERE signature = ?", (signature,)
            ).rowcount

    # ---------------------------------------------------------------- reading

    def fresh(self, signature: str) -> dict[str, str]:
        """``entry_id -> content_hash`` for one embedder.

        The caller compares against the index's own hash to decide what needs
        embedding. An entry whose text has not changed is never paid for twice.
        """
        rows = self._conn.execute(
            "SELECT entry_id, content_hash FROM vectors WHERE signature = ?", (signature,)
        )
        return {r["entry_id"]: r["content_hash"] for r in rows}

    def count(self, signature: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM vectors WHERE signature = ?", (signature,)
        ).fetchone()
        return int(row["n"]) if row else 0

    def get(self, entry_id: str, signature: str) -> list[float] | None:
        row = self._conn.execute(
            "SELECT vector FROM vectors WHERE entry_id = ? AND signature = ?",
            (entry_id, signature),
        ).fetchone()
        return unpack(row["vector"]) if row else None

    def nearest(
        self,
        vector: list[float],
        signature: str,
        *,
        limit: int = 10,
        exclude: str | None = None,
        floor: float = 0.0,
    ) -> list[tuple[str, float]]:
        """The closest entries by cosine, nearest first.

        A brute-force scan, deliberately. At a few thousand entries this is a
        millisecond of pure Python, and an approximate index would be a second
        structure to keep in step with the journal for a saving nobody could
        feel. The day it is slow is the day it earns ``sqlite-vec``.

        Vectors are stored normalised, so cosine is a dot product. ``floor``
        exists because a nearest-neighbour query always returns something: on a
        journal about one subject the tenth-nearest entry may be unrelated, and
        passing that to the connector as a candidate spends money proposing a
        link between two thoughts that have nothing to do with each other.
        """
        rows = self._conn.execute(
            "SELECT entry_id, vector FROM vectors WHERE signature = ?"
            + (" AND entry_id != ?" if exclude else ""),
            (signature, exclude) if exclude else (signature,),
        )
        scored = []
        for row in rows:
            other = unpack(row["vector"])
            if len(other) != len(vector):
                continue
            score = sum(a * b for a, b in zip(vector, other, strict=True))
            if score >= floor:
                scored.append((row["entry_id"], score))
        scored.sort(key=lambda pair: -pair[1])
        return scored[:limit]
