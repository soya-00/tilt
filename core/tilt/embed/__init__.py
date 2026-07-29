"""Embeddings — the half of retrieval that needs a key.

Everything else in Tilt works offline. This does not, and the reason is
structural rather than a gap waiting to be filled: the whole point of a vector
is to relate two entries that share no words, and what makes them related is
usually a fact about the world rather than about your journal. Nothing fitted on
your own writing can supply that. An offline embedder was built, measured, and
removed — it separated subjects well and bridged nothing, which is the one job
it was there to do.

So :func:`build_embedder` returns ``None`` without a key, and every caller
treats that as "no second ranker" rather than as an error. Reciprocal rank
fusion already degrades to a single list, and the connector already had a
candidate set before vectors existed. The app is smaller without a key, not
broken — and Settings says which capabilities are asleep rather than leaving
you to notice.
"""

from __future__ import annotations

from tilt.config import Settings
from tilt.embed.base import Embedder, EmbeddingError

# What stops working without a key, in the user's words rather than ours.
# Surfaced by /status so Settings can show it beside the key field.
DORMANT_WITHOUT_KEY = [
    (
        "Connections between thoughts that share no words",
        "Finding these means comparing meaning rather than vocabulary, which "
        "needs a model that has read more than you have.",
    ),
    (
        "Reading a link or watching a video",
        "There is no page to fetch and no video to watch without one.",
    ),
]


def build_embedder(settings: Settings) -> Embedder | None:
    """The configured embedder, or ``None`` when there is nothing to use.

    Mirrors :func:`tilt.agents.build_provider`, except that the offline branch
    returns nothing instead of a stand-in. A stand-in here would be worse than
    absent: it would put a vector ranker in the pipeline that changes no ranking
    and let everyone believe the capability was present.
    """
    if not settings.embeddings_enabled or not settings.gemini_api_key:
        return None

    from tilt.embed.gemini import GeminiEmbedder

    return GeminiEmbedder(api_key=settings.gemini_api_key, dims=settings.embed_dims)


__all__ = ["DORMANT_WITHOUT_KEY", "Embedder", "EmbeddingError", "build_embedder"]
