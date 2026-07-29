"""Retrieval.

Two rankers when there is a key, one when there is not. BM25 finds the words you
typed; the vector ranker finds entries about the same thing that use none of
them. Fusing them was designed for from the start, which is why adding the
second was a matter of passing another list rather than reworking any caller.

Without a key there is no embedder and the fusion sees a single list, which it
already handles — the results are simply the lexical ones, as they were before.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from tilt.agents.parsing import STOPWORDS
from tilt.embed import Embedder, EmbeddingError
from tilt.models import Entry
from tilt.store.index import Index
from tilt.store.vectors import VectorStore

RRF_K = 60
"""Damping constant. 60 is the value from the original RRF paper and behaves
well when one ranker is much noisier than the other."""

_FTS_SPECIAL = re.compile(r'[":^*(){}\[\]-]')


def sanitize_query(raw: str) -> str:
    """Make arbitrary user text safe for an FTS5 MATCH, and worth matching on.

    Two jobs. Escaping, because users type apostrophes and hyphens constantly
    and unescaped they raise ``sqlite3.OperationalError`` and the search box
    appears broken.

    And dropping stopwords, because FTS5 has none and BM25 rewards rarity. Feed
    it a whole entry — which is what ``context_for`` does — and a word like
    "is" can be the rarest term in the query, ranking an unrelated entry above
    twenty that are genuinely about the subject. Measured on a corpus of twenty
    near-identical baking notes, an entry about a scheduler ranked *first* for a
    baking entry, on the strength of sharing the word "is".

    Stripped only when something is left. Searching for "the" should find
    entries containing "the" rather than silently finding nothing.
    """
    cleaned = _FTS_SPECIAL.sub(" ", raw).strip()
    terms = [t for t in cleaned.split() if t]
    content = [t for t in terms if t.lower() not in STOPWORDS]
    return " OR ".join(f'"{t}"' for t in (content or terms))


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


def search(
    index: Index,
    query: str,
    *,
    limit: int = 20,
    vectors: VectorStore | None = None,
    embedder: Embedder | None = None,
) -> list[Entry]:
    ranked: list[Sequence[Entry]] = []

    match = sanitize_query(query)
    if match:
        ranked.append([entry for entry, _ in index.search_fts(match, limit=limit * 2)])

    semantic = _semantic(index, query, limit=limit * 2, vectors=vectors, embedder=embedder)
    if semantic:
        ranked.append(semantic)

    return reciprocal_rank_fusion(*ranked, limit=limit) if ranked else []


def _semantic(
    index: Index,
    query: str,
    *,
    limit: int,
    vectors: VectorStore | None,
    embedder: Embedder | None,
) -> list[Entry]:
    """The vector half, or nothing at all.

    Embedding the query is one hosted call per search, which is why this is not
    free and why a failure must never take the search box down with it: a
    network hiccup degrades results to lexical rather than showing an error over
    something the user typed.
    """
    if vectors is None or embedder is None or not query.strip():
        return []
    try:
        vector = embedder.embed([query])[0]
    except EmbeddingError:
        return []
    found = [index.get(eid) for eid, _ in vectors.nearest(vector, embedder.signature, limit=limit)]
    return [e for e in found if e is not None]
