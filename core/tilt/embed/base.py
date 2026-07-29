"""What an embedder has to be.

A protocol with one implementation today, kept because the alternative is
callers importing the Gemini client directly and every one of them needing to
know it might not be there. The absence is expressed by ``build_embedder``
returning ``None``, not by a second class pretending to embed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class EmbeddingError(Exception):
    """The embedder could not produce vectors for this text."""


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors that can be compared by cosine."""

    @property
    def signature(self) -> str:
        """Identifies which embedder produced a vector — ``gemini/<model>/768``.

        Every read is scoped to it. Cosine between vectors from two different
        models is a number with no meaning, and the failure would look like bad
        recommendations rather than like a bug, so the two never meet: change
        the model and the old rows are dropped rather than mixed in.
        """
        ...

    @property
    def dims(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Vectors for a batch, in the order given.

        Batched because the hosted path is a network round trip and one call per
        entry would make a first run over a real journal absurd.
        """
        ...
