"""When the jobs run.

Two different shapes of schedule, for two different reasons.

The sweep is an *interval*: it exists to drain a backlog, and a backlog can
appear at any hour. Running it every quarter of an hour costs one indexed query
when there is nothing waiting, which is almost always.

The theme-keeper is a *cron*: it rearranges the sidebar, and doing that while
someone is looking at it is disorienting. Overnight it is.

The weekly look back is a cron for a third reason again: it is about a period
rather than about a backlog, and running it more often would mean reporting on
a week that has barely changed since the last report.

And a fourth job watches the three crons, because a cron only fires if the
process is alive at that minute. On a laptop that sleeps at night, none of them
ever did. See :mod:`tilt.jobs.overdue`.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from tilt.agents.ledger import MeteredProvider
from tilt.config import Settings
from tilt.jobs.overdue import catch_up
from tilt.jobs.runner import run_job
from tilt.journal import Journal

log = logging.getLogger(__name__)

KEEPER_MINUTE = 17
"""Not on the hour. Everything else that runs at 3am runs at 3:00."""

SCOUT_MINUTE = 41
"""Same reason, and not the keeper's minute either — two model-calling jobs
waking together would race for the same ceiling check."""

WEEK_MINUTE = 53
"""Its own minute, for consistency rather than for contention: the weekly pass
makes no model call and could not race anything for the ceiling."""


class Schedule:
    """The scheduled half of the agent layer.

    Deliberately thin. Nothing here decides anything — it holds the triggers and
    hands off to :func:`tilt.jobs.runner.run_job`, so every job behaves
    identically whether time started it or the user pressed a button.
    """

    def __init__(self, journal: Journal, provider: MeteredProvider, settings: Settings) -> None:
        self._journal = journal
        self._provider = provider
        self._settings = settings
        self._scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        if self._scheduler is not None:
            return
        scheduler = AsyncIOScheduler(
            job_defaults={
                # A laptop that was asleep for two days must not wake up and run
                # forty missed sweeps. Coalesce them into one, and let a run that
                # is more than a few minutes late simply not happen.
                #
                # For the crons that is not a policy, it is a hole: this setting
                # only governs a fire time that passed while the scheduler was
                # alive, and says nothing about the hours the process did not
                # exist for. The `overdue` job below is what covers those.
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            }
        )
        scheduler.add_job(
            self._run,
            IntervalTrigger(minutes=self._settings.sweep_interval_minutes),
            args=["sweep"],
            id="sweep",
            name="Catch up on unfiled entries",
        )
        # The three jobs below are crons, and a cron only fires if the process
        # is alive at that minute. On a laptop that sleeps at night and opens in
        # the morning, none of them had ever run. This ticks on the sweep's
        # interval — the property the crons lack — and asks the index whether
        # each is overdue. See :mod:`tilt.jobs.overdue`.
        scheduler.add_job(
            self._catch_up,
            IntervalTrigger(minutes=self._settings.sweep_interval_minutes),
            id="overdue",
            name="Run what the schedule missed",
        )
        scheduler.add_job(
            self._run,
            CronTrigger(hour=self._settings.theme_keeper_hour, minute=KEEPER_MINUTE),
            args=["themes"],
            id="themes",
            name="Tidy the folders",
        )
        # An interval rather than a cron, like the sweep and for the same
        # reason: this drains a backlog, and a backlog appears whenever you
        # write. Slower than the sweep because nothing waits on it — an entry
        # embedded an hour late is only missing from the vector half of
        # retrieval for that hour, whereas an unfiled one is invisible.
        scheduler.add_job(
            self._run,
            IntervalTrigger(minutes=self._settings.embed_interval_minutes),
            args=["vectors"],
            id="vectors",
            name="Embed new entries",
        )
        # A cron rather than an interval, and the only job here whose schedule
        # is about the reader rather than the backlog. Nothing accumulates that
        # this drains — it goes and looks — so running it more often would only
        # fill the brief faster than anyone empties it.
        scheduler.add_job(
            self._run,
            CronTrigger(hour=self._settings.scout_hour, minute=SCOUT_MINUTE),
            args=["scout"],
            id="scout",
            name="Look for something worth reading",
        )
        # Weekly, and the only job here that cannot spend anything: it runs two
        # queries over what the index and the vector store already hold. That is
        # what makes an unattended weekly pass defensible at all — the expensive
        # half happens when somebody presses the button on what it found.
        scheduler.add_job(
            self._run,
            CronTrigger(day_of_week="sun", hour=self._settings.week_hour, minute=WEEK_MINUTE),
            args=["week"],
            id="week",
            name="Look back over the week",
        )
        scheduler.start()
        self._scheduler = scheduler
        log.info(
            "scheduler started: sweep every %dm, folders at %02d:%02d",
            self._settings.sweep_interval_minutes,
            self._settings.theme_keeper_hour,
            KEEPER_MINUTE,
        )

    async def _catch_up(self) -> None:
        try:
            await catch_up(self._journal, self._provider)
        except Exception:
            log.exception("the overdue check failed")

    async def _run(self, name: str) -> None:
        # Nothing is waiting on the result and there is no one to show an error
        # to, so a failure has to end here — an exception escaping into
        # APScheduler's loop would be logged once and lose the run record.
        try:
            await run_job(name, self._journal, self._provider)
        except Exception:
            log.exception("scheduled job %s failed", name)

    def shutdown(self) -> None:
        if self._scheduler is None:
            return
        # Not waiting: shutdown runs during application teardown, and a job
        # holding a model call open would keep the process alive past the point
        # where the desktop shell expects it to be gone.
        self._scheduler.shutdown(wait=False)
        self._scheduler = None
