"""Retrieval.

Today this ranks with FTS5/BM25 only. The fusion step is already in place so
that adding a vector ranker later is a matter of passing a second ranked list to
:func:`reciprocal_rank_fusion` rather than reworking every caller.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from tilt.models import Entry
from tilt.store.index import Index

RRF_K = 60
"""Damping constant. 60 is the value from the original RRF paper and behaves
well when one ranker is much noisier than the other."""

_FTS_SPECIAL = re.compile(r'[":^*(){}\[\]-]')


def sanitize_query(raw: str) -> str:
    """Make arbitrary user text safe for an FTS5 MATCH.

    Users type apostrophes and hyphens constantly; unescaped they raise
    ``sqlite3.OperationalError`` and the search box appears broken.
    """
    cleaned = _FTS_SPECIAL.sub(" ", raw).strip()
    terms = [t for t in cleaned.split() if t]
    return " OR ".join(f'"{t}"' for t in terms)


def reciprocal_rank_fusion(
    *ranked_lists: Sequence[Entry], k: int = RRF_K, limit: int = 20
) -> list[Entry]:
    """Fuse ranked lists by reciprocal rank.

    Scores from different rankers are not comparable (BM25 is unbounded and
    lower-is-better; cosine is bounded and higher-is-better), so we fuse on
    position instead of score.
    """
    scores: dict[str, float] = {}
    seen: dict[str, Entry] = {}
    for ranked in ranked_lists:
        for rank, entry in enumerate(ranked):
            scores[entry.id] = scores.get(entry.id, 0.0) + 1.0 / (k + rank + 1)
            seen.setdefault(entry.id, entry)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [seen[eid] for eid, _ in ordered[:limit]]


def search(index: Index, query: str, *, limit: int = 20) -> list[Entry]:
    match = sanitize_query(query)
    if not match:
        return []
    lexical = [entry for entry, _ in index.search_fts(match, limit=limit * 2)]
    # Second ranker (vector kNN) slots in here.
    return reciprocal_rank_fusion(lexical, limit=limit)
