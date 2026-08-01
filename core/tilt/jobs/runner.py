"""Running a job and leaving a record that it ran.

The record is the point. A scheduled pass that fails at 3am and says nothing is
worse than no scheduled pass at all, because the app now looks like it is
keeping up when it has quietly stopped. Every run writes a row whether it
succeeded, failed, or stopped at the spending ceiling.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from tilt.agents.ledger import MeteredProvider
from tilt.jobs.scout import scout
from tilt.jobs.sweep import sweep
from tilt.jobs.themes import keep_themes
from tilt.jobs.vectors import embed_pending
from tilt.jobs.week import look_back
from tilt.journal import Journal
from tilt.models import AgentRun, JobSummary, utcnow
from tilt.store.files import new_id

log = logging.getLogger(__name__)

Job = Callable[[Journal, MeteredProvider], Awaitable[JobSummary]]

JOBS: dict[str, Job] = {
    "sweep": sweep,
    "themes": keep_themes,
    "vectors": embed_pending,
    "scout": scout,
    "week": look_back,
}
"""The jobs a schedule can run, and the ones the UI can trigger by name."""


async def run_job(name: str, journal: Journal, provider: MeteredProvider) -> JobSummary:
    """Run one job, recording the outcome even when it raises."""
    job = JOBS.get(name)
    if job is None:
        raise KeyError(name)

    # Cost stays at zero here on purpose: the model calls inside the job each
    # record their own priced row, and totalling them again on this one would
    # double the month's spend.
    run = AgentRun(
        id=new_id(), job=name, model=provider.name, status="running", started=utcnow()
    )
    try:
        summary = await job(journal, provider)
    except Exception as exc:
        run.status = "error"
        run.finished = utcnow()
        run.error = str(exc)[:500]
        journal.index.record_run(run)
        log.exception("job %s failed", name)
        raise

    run.status = "paused" if summary.paused else "ok"
    run.detail = summary.detail
    run.finished = utcnow()
    journal.index.record_run(run)
    log.info("job %s: %s", name, summary.detail)
    return summary
