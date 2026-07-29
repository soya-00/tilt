"""Keeping the vector store level with the journal.

Runs on a schedule rather than on the write path, for the same reason the sweep
does: embedding is a network round trip and a bill, and neither belongs between
pressing Enter and seeing your thought on screen.

It is also the only job that does nothing at all without a key, and it says so
rather than reporting a quiet success. A job that returns "0 considered" when
the real answer is "this cannot run" is how a capability goes missing for weeks
without anybody noticing.
"""

from __future__ import annotations

import logging

from tilt.agents.ledger import MeteredProvider
from tilt.embed import EmbeddingError
from tilt.journal import Journal
from tilt.models import JobSummary
from tilt.store.index import content_hash

log = logging.getLogger(__name__)

JOB = "vectors"

BATCH = 128
"""Entries embedded per pass.

Bounded so a first run over a large journal spends predictably rather than
arriving as one surprising charge. The remainder is picked up next run, and the
content hash means nothing already done is ever paid for twice."""


async def embed_pending(
    journal: Journal, provider: MeteredProvider, *, batch: int = BATCH
) -> JobSummary:
    """Embed what is new or edited, and forget what is gone.

    ``provider`` is unused — embedding does not go through the agent provider —
    but the signature is the one every job has, which is what lets the runner
    treat them all the same and the UI trigger any of them by name.
    """
    embedder = journal.embedder
    store = journal.vectors
    if embedder is None or store is None:
        return JobSummary(
            job=JOB,
            detail=(
                "Needs a Gemini key. Connections between thoughts that share no "
                "words are the one thing Tilt cannot do on its own."
            ),
        )

    signature = embedder.signature
    known = store.fresh(signature)
    entries = journal.index.all_entries()

    # An entry whose text has not changed since it was embedded is never paid
    # for again; one that was edited is, because its meaning may have moved.
    pending = [
        e
        for e in entries
        if e.body.strip() and known.get(e.id) != content_hash(e.body)
    ]

    # Vectors for entries that no longer exist keep turning up as neighbours of
    # the ones that do. Deletions clean up as they happen; this catches whatever
    # was removed while the app was not running.
    live = {e.id for e in entries}
    for stale in set(known) - live:
        store.forget(stale)

    summary = JobSummary(job=JOB, considered=len(pending))
    if not pending:
        summary.detail = f"{len(known)} entries embedded, nothing new."
        return summary

    window = pending[:batch]
    try:
        vectors = await _embed(embedder, [e.body for e in window])
    except EmbeddingError as exc:
        log.warning("embedding failed: %s", exc)
        summary.detail = f"Embedding failed: {exc}"
        return summary

    for entry, vector in zip(window, vectors, strict=True):
        store.put(entry.id, signature, content_hash(entry.body), vector)

    summary.filed = len(window)
    remaining = len(pending) - len(window)
    summary.detail = f"{len(window)} embedded" + (
        f", {remaining} waiting for the next pass." if remaining else "."
    )
    return summary


async def _embed(embedder, texts: list[str]) -> list[list[float]]:
    """Off the event loop when the embedder knows how, since the SDK blocks."""
    if hasattr(embedder, "embed_async"):
        return await embedder.embed_async(texts)
    return embedder.embed(texts)
