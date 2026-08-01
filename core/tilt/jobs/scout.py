"""Looking for things worth reading, once a day.

Daily rather than hourly, and the interval is the design. An hourly scout would
propose something before you had finished reading the last thing it proposed,
and a list that grows faster than it is read is a backlog whatever it is called.

The job never touches the journal. It writes to the brief and stops there, so
the most it can cost you while you are not looking is a search and one triage
call — the expensive step is reading, and reading only happens when you choose
something.
"""

from __future__ import annotations

import logging

import httpx

from tilt.agents.ledger import MeteredProvider
from tilt.agents.scout import gather, triage, unseen
from tilt.journal import Journal
from tilt.models import BriefItem, BriefOrigin, JobSummary, utcnow
from tilt.store.brief import BriefStore, normalise
from tilt.store.files import new_id

log = logging.getLogger(__name__)

JOB = "scout"


async def look(
    journal: Journal,
    provider: MeteredProvider,
    *,
    brief: BriefStore | None = None,
    feeds: list[str] | None = None,
    persona_instruction: str = "",
    client: httpx.AsyncClient | None = None,
) -> JobSummary:
    """One pass: gather, forget what is already known, triage, propose.

    Returns what it did in a sentence, like every other unattended job. Finding
    nothing is the common case and is reported as such rather than as a failure
    — most of what appears on any given day answers nothing anybody asked.
    """
    if brief is None:
        return JobSummary(job=JOB, detail="No brief configured; nothing to write to.")

    sources = feeds or []
    candidates = await gather(journal, sources, client=client)
    if not candidates:
        # Two causes, said apart. They used to share one sentence — "no feeds
        # configured, or none of them had anything" — and that sentence is what
        # hid a bug for a fortnight: the job was reading settings from a
        # directory that no longer existed, saw no feeds, and reported something
        # that was true of a perfectly healthy morning.
        return JobSummary(
            job=JOB,
            detail=(
                f"Nothing turned up from your {len(sources)} feeds today."
                if sources
                else "No feeds configured, so there is nowhere to look."
            ),
        )

    # Both halves of the memory: what the journal has already read, and what
    # the brief has already offered — including what you turned down. The
    # journal stores URLs as they arrived, so they are normalised here; the
    # brief's are normalised already, and comparing the two forms would let the
    # same paper through on a trailing slash.
    known = {*(normalise(u) for u in journal.index.known_urls()), *brief.seen()}
    fresh = unseen(candidates, known)
    summary = JobSummary(job=JOB, considered=len(fresh))
    if not fresh:
        summary.detail = f"{len(candidates)} turned up, all of them already seen."
        return summary

    picks = await triage(
        journal, provider, fresh, persona_instruction=persona_instruction
    )
    if not picks:
        summary.detail = f"Read {len(fresh)} titles, none worth your time."
        return summary

    now = utcnow()
    for finding, why, tags in picks:
        brief.save(
            BriefItem(
                id=new_id(),
                title=finding.title[:200],
                url=finding.url,
                why=why or f"Turned up in {finding.source}.",
                origin=BriefOrigin.SCOUT,
                tags=tags,
                created=now,
            )
        )

    summary.filed = len(picks)
    summary.detail = (
        f"Read {len(fresh)} titles, put {len(picks)} in the brief. "
        "Nothing is in your journal until you read one."
    )
    return summary


async def scout(journal: Journal, provider: MeteredProvider) -> JobSummary:
    """What the scheduler and the Settings button call.

    Builds its own brief and feed list rather than taking them as arguments,
    because every job in the registry has the same two-parameter shape and the
    alternative is threading a context object through the runner for one job's
    sake. The brief is deliberately *not* hung off `Journal` the way vectors
    are: nothing in it is part of the journal until you read it, and putting it
    there would blur exactly the line this feature depends on.
    """
    from tilt.settings_store import SettingsStore

    # From the same file the app writes. This has been wrong twice — first a
    # path inside the journal that the support-dir split abandoned, and now the
    # support path that the move back into the journal abandoned — and both
    # times it failed silently, because loading a file that is not there yields
    # defaults rather than an error. Hence the test that asserts the scheduled
    # scout can actually see the feeds you configured.
    runtime = SettingsStore(journal.data_dir / "settings.json").load()
    return await look(
        journal,
        provider,
        brief=BriefStore(journal.data_dir / "brief"),
        feeds=runtime.feeds,
    )
