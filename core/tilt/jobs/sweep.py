"""The catch-up pass.

The interface files an entry the moment you keep it. Plenty of entries never go
through that path: a thought caught with ⌥Space while the journal window was
closed, one written when the budget ceiling had already stopped scheduled work,
one whose filing call failed against a network that was down. Nothing ever
revisits those — they stay untagged, unconnected, and invisible to the sidebar
forever.

This is what revisits them.
"""

from __future__ import annotations

from datetime import timedelta

from tilt.agents.base import AgentError
from tilt.agents.categorize import categorize
from tilt.agents.connect import connect
from tilt.agents.ledger import BudgetExceeded, MeteredProvider
from tilt.journal import Journal
from tilt.models import JobSummary, utcnow

JOB = "sweep"

SETTLE = timedelta(minutes=3)
"""How long an entry must sit before the sweep will touch it.

The interface is already filing anything written just now. Without a quiet
period the two would race and the same judgement would be paid for twice."""

BATCH = 12
"""Entries per pass.

A first run against an imported journal of a thousand entries must not fire two
thousand model calls in one go. The backlog drains a batch at a time, newest
first, so the most recent unfiled thought is always the one that gets attention
soonest."""

STRIKES = 2
"""Consecutive failures before the pass gives up.

One entry the model chokes on should not stop the sweep; a provider that is
down should not cost twelve identical failures."""


async def sweep(
    journal: Journal, provider: MeteredProvider, *, batch: int = BATCH
) -> JobSummary:
    """File and judge whatever the interface never got to.

    Runs non-interactively, so it stops at 80% of the monthly ceiling and leaves
    the remainder for work you are present for.
    """
    settled_before = (utcnow() - SETTLE).isoformat()
    pending = journal.index.backlog(limit=batch, settled_before=settled_before)

    summary = JobSummary(job=JOB, considered=len(pending))
    strikes = 0

    for entry, needs_filing, needs_judging in pending:
        try:
            if needs_filing:
                await categorize(journal, provider, entry.id, interactive=False)
                summary.filed += 1
            if needs_judging:
                links = await connect(journal, provider, entry.id, interactive=False)
                summary.connected += len(links)
            strikes = 0
        except BudgetExceeded:
            # Not a failure. The ceiling did its job; the backlog is still there
            # and the next pass resumes from the same place.
            summary.paused = True
            break
        except AgentError:
            strikes += 1
            if strikes >= STRIKES:
                break

    summary.detail = _describe(summary)
    return summary


def _describe(summary: JobSummary) -> str:
    if not summary.considered:
        return "nothing waiting"
    parts = [f"{summary.considered} considered"]
    if summary.filed:
        parts.append(f"{summary.filed} filed")
    if summary.connected:
        parts.append(f"{summary.connected} connected")
    if summary.paused:
        parts.append("paused at the spending ceiling")
    return ", ".join(parts)
