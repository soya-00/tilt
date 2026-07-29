"""When the jobs run.

Two different shapes of schedule, for two different reasons.

The sweep is an *interval*: it exists to drain a backlog, and a backlog can
appear at any hour. Running it every quarter of an hour costs one indexed query
when there is nothing waiting, which is almost always.

The theme-keeper is a *cron*: it rearranges the sidebar, and doing that while
someone is looking at it is disorienting. Overnight it is.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from tilt.agents.ledger import MeteredProvider
from tilt.config import Settings
from tilt.jobs.runner import run_job
from tilt.journal import Journal

log = logging.getLogger(__name__)

KEEPER_MINUTE = 17
"""Not on the hour. Everything else that runs at 3am runs at 3:00."""

SCOUT_MINUTE = 41
"""Same reason, and not the keeper's minute either — two model-calling jobs
waking together would race for the same ceiling check."""


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
        scheduler.start()
        self._scheduler = scheduler
        log.info(
            "scheduler started: sweep every %dm, folders at %02d:%02d",
            self._settings.sweep_interval_minutes,
            self._settings.theme_keeper_hour,
            KEEPER_MINUTE,
        )

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
