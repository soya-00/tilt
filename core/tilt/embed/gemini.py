"""Hosted embeddings.

The only thing in the app that can relate two entries sharing no words. That is
not a limitation of the offline provider — it is a fact about where the relation
lives. "Proofing dough" and "a polling interval" are alike because waiting is a
thing in the world, not because of anything in your journal, and nothing fitted
on your own writing can know it. A model that read far more than you have can.
"""

from __future__ import annotations

import asyncio
import logging

from tilt.agents.redact import redact
from tilt.embed.base import EmbeddingError

log = logging.getLogger(__name__)

MODEL = "gemini-embedding-001"

DIMS = 768
"""Truncated from the model's native width, which it supports directly.

3072 floats an entry is four times the storage and four times the cosine for a
difference in retrieval quality nobody has ever noticed at journal scale."""

BATCH = 64
"""Entries per request. A first run over a real journal is hundreds of entries,
and one request each would take minutes and rate-limit besides."""

COST_PER_M = 0.15
"""USD per million input tokens. Recorded rather than ignored: embedding is the
first thing in the app that spends money without the user asking for anything,
and spend that does not reach the ledger is spend nobody can see."""


class GeminiEmbedder:
    needs_fitting = False

    def __init__(self, api_key: str, model: str = MODEL, dims: int = DIMS) -> None:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise EmbeddingError(
                "google-genai is not installed. Install the 'gemini' extra to embed."
            ) from exc
        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._dims = dims

    @property
    def signature(self) -> str:
        return f"gemini/{self._model}/{self._dims}"

    @property
    def dims(self) -> int:
        return self._dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            out.extend(self._batch(texts[start : start + BATCH]))
        return out

    def _batch(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        try:
            response = self._client.models.embed_content(
                model=self._model,
                contents=texts,
                config=types.EmbedContentConfig(
                    output_dimensionality=self._dims,
                    # Both sides of a comparison must be embedded the same way,
                    # and this is a symmetric task: every entry is both a thing
                    # being looked up and a thing being looked up against.
                    task_type="SEMANTIC_SIMILARITY",
                ),
            )
        except Exception as exc:  # noqa: BLE001 - surface as one failure mode
            # Redacted before it is logged as well as before it is relayed —
            # see the note in agents/gemini.py. The log was the weaker path.
            safe = redact(str(exc))
            log.error("embedding failed: %s", safe)
            raise EmbeddingError(f"Embedding failed: {safe}") from exc

        vectors = [list(e.values or []) for e in (response.embeddings or [])]
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"Asked for {len(texts)} embeddings and got {len(vectors)}."
            )
        # Normalised here rather than at every comparison, so cosine is a dot
        # product everywhere downstream. Truncated output is not unit length.
        return [_unit(v) for v in vectors]

    async def embed_async(self, texts: list[str]) -> list[list[float]]:
        """The SDK call is blocking, and the callers are async.

        Off the event loop, so embedding a few hundred entries in a scheduled
        job does not stall every request the service is serving.
        """
        return await asyncio.to_thread(self.embed, texts)


def _unit(vector: list[float]) -> list[float]:
    norm = sum(v * v for v in vector) ** 0.5
    return [v / norm for v in vector] if norm else vector
