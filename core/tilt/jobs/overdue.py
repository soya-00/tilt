"""Jobs that were supposed to have run by now.

Three of the five jobs are crons: the folder keeper at 03:17, the scout at
06:41, the weekly look-back on Sunday evening. Each hour was chosen for a
reason — the keeper rearranges the sidebar and should not do it while you are
looking at it, the scout should have finished before you sit down.

**A cron only fires if the process is alive at that minute.** The sweep and the
embed pass are intervals, so they are scheduled relative to start-up and heal
themselves: open the app at any hour and the sweep runs within fifteen minutes.
A cron has no such property. Close the laptop at midnight and 03:17 never
happens; open it at nine and APScheduler schedules the *next* 03:17, which is
tomorrow, which is also a night the laptop was shut.

So on the machine this app was written for — a laptop, asleep at night, opened
in the morning — the keeper, the scout and the weekly pass never ran at all.
Not rarely. Never. Folder splitting and refiling live in the keeper, which is
why nothing was ever proposed.

`misfire_grace_time` does not fix it. That governs a job whose fire time passed
while the scheduler was alive; it knows nothing about the hours a process did
not exist for, and a scheduler with no persistent job store starts each launch
with no memory of what it missed.

What fixes it is asking a different question. Rather than "did the moment
arrive", ask **"has it been long enough since this last ran"** — which the index
can answer, because every run leaves a row there whether it succeeded, failed,
or stopped at the ceiling. That is the same record Settings shows you.

This runs on the sweep's interval, so it inherits the property the crons lack.
It costs one indexed query per job, and on a machine that has been awake all
along it finds nothing to do.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from tilt.agents.ledger import MeteredProvider
from tilt.journal import Journal
from tilt.models import utcnow

log = logging.getLogger(__name__)

PERIODS: dict[str, timedelta] = {
    "themes": timedelta(days=1),
    "scout": timedelta(days=1),
    "week": timedelta(days=7),
}
"""How often each cron job is meant to happen.

Only the crons. The sweep and the embed pass are intervals and already recover
on their own; watching them here would be a second mechanism for a problem that
does not exist."""

SLACK = timedelta(hours=2)
"""How far past its period a job must be before this steps in.

Not zero, and the reason is a race rather than politeness. A job that ran at
06:41 becomes exactly one day old at 06:41 the next morning — the same minute
its cron fires. A tick landing anywhere in that minute, or in the few that
follow while the cron's run is still in flight, would see a job past its period
and run it a second time. Waiting two hours means the cron's run has been
recorded long since, and the job is not overdue at all.

Two hours is far shorter than the day a sleeping laptop costs, so the ordinary
case stays with the cron and this only covers the case the cron cannot.

What it does not close is drift. A job this ran late — at 05:00, say, because
that is when the laptop opened — is due again at 07:00 the next day rather than
at 06:41, so on that one morning both may run. The cost is one extra triage
call and at most two extra brief items, against a bug where the job never ran
at all; closing it properly would mean teaching this to read the cron's next
fire time, which is a great deal of machinery for a duplicate that costs a
penny."""

MAX_PER_TICK = 1
"""One at a time.

Opening a laptop after a fortnight away makes all three overdue at once, and
running them together would spend three jobs' worth of model calls in the first
minute of a session. They are each a day or a week late already; another quarter
of an hour is nothing."""


def due(journal: Journal) -> list[str]:
    """Which cron jobs are overdue, longest-overdue first.

    A job with no record at all is treated as never run, which is exactly what
    it is — on a fresh journal, and on every journal that has been closed at
    3am since the day it was made.
    """
    now = utcnow()
    overdue: list[tuple[timedelta, str]] = []
    for name, period in PERIODS.items():
        last = journal.index.last_run(name)
        if last is None:
            overdue.append((timedelta.max, name))
            continue
        late = now - last - period
        if late >= SLACK:
            overdue.append((late, name))
    # Sorted rather than negated: "never run" is `timedelta.max`, and negating
    # that overflows.
    overdue.sort(key=lambda p: p[0], reverse=True)
    return [name for _, name in overdue]


async def catch_up(journal: Journal, provider: MeteredProvider) -> list[str]:
    """Run what should already have run. Returns the names it started.

    Imported here rather than at module scope: `tilt.jobs.runner` imports every
    job including this one, so a top-level import would be a cycle.
    """
    from tilt.jobs.runner import run_job

    started = []
    for name in due(journal)[:MAX_PER_TICK]:
        log.info("running %s late — its schedule was missed", name)
        try:
            await run_job(name, journal, provider)
        except Exception:
            # `run_job` has already written the failure row, which is what stops
            # this retrying every fifteen minutes: the row is a run, and a run
            # resets the clock.
            log.exception("late run of %s failed", name)
        started.append(name)
    return started
