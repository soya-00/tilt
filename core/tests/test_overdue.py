"""The jobs that never ran.

Three of the five are crons, and a cron only fires if the process is alive at
that minute. On a laptop — asleep at 03:17, asleep at 06:41, opened at nine —
the folder keeper, the scout and the weekly pass had never run once. Not
rarely. Never.

The bug was invisible because every symptom of it looks like something else:
the brief stays empty, which reads as "the scout found nothing"; no folder is
ever proposed for splitting, which reads as "my folders are fine".
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tilt.jobs import overdue
from tilt.jobs.overdue import PERIODS, SLACK, catch_up, due
from tilt.journal import Journal
from tilt.models import AgentRun, utcnow
from tilt.store.files import new_id
from tilt.store.index import Index


def ran(index: Index, job: str, *, ago: timedelta) -> None:
    when = utcnow() - ago
    index.record_run(
        AgentRun(id=new_id(), job=job, model="echo", status="ok", started=when, finished=when)
    )


# ------------------------------------------------------------------ the bug


def test_a_journal_that_has_never_run_them_is_overdue_for_all_three(journal: Journal) -> None:
    """The state every journal is in after one night with the laptop shut."""
    assert set(due(journal)) == set(PERIODS)


def test_the_scout_is_overdue_a_day_after_it_last_looked(journal: Journal) -> None:
    """The reported symptom. A cron at 06:41 on a machine asleep at 06:41 means
    the scout looks once — the day you happened to be awake for it — and then
    never again."""
    ran(journal.index, "scout", ago=timedelta(days=1) + SLACK)

    assert "scout" in due(journal)


def test_a_job_that_ran_on_time_is_not_overdue(journal: Journal) -> None:
    """The machine that was left on overnight. The cron fired, and this must
    find nothing to do — otherwise it is a second scheduler racing the first."""
    for name in PERIODS:
        ran(journal.index, name, ago=timedelta(minutes=5))

    assert due(journal) == []


def test_the_weekly_pass_is_not_chased_daily(journal: Journal) -> None:
    """Each job is measured against its own period. A weekly job two days old is
    early, not late."""
    ran(journal.index, "week", ago=timedelta(days=2))
    ran(journal.index, "themes", ago=timedelta(days=2))
    ran(journal.index, "scout", ago=timedelta(minutes=5))

    assert due(journal) == ["themes"]


# ------------------------------------------------------------------- the race


def test_it_does_not_race_the_cron_it_is_covering_for(journal: Journal) -> None:
    """The minute a job turns a day old is the minute its cron fires.

    A job that ran at 06:41 is exactly one day old at 06:41 the next morning.
    Without `SLACK`, a tick landing in that minute — or in the few that follow
    while the cron's own run is still in flight — sees a job past its period and
    runs it a second time. This is that moment: past the period, and still the
    cron's to do.
    """
    ran(journal.index, "scout", ago=timedelta(days=1, minutes=1))

    assert "scout" not in due(journal)


def test_it_does_step_in_once_the_cron_plainly_did_not(journal: Journal) -> None:
    """The other side of the same boundary, so the constant is pinned from both
    directions rather than only from the safe one."""
    ran(journal.index, "scout", ago=timedelta(days=1) + SLACK + timedelta(minutes=1))

    assert "scout" in due(journal)


# ------------------------------------------------------ what it does about it


async def test_it_runs_the_job_and_leaves_a_record(journal: Journal, provider) -> None:
    started = await catch_up(journal, provider)

    assert started == [max(PERIODS, key=lambda n: PERIODS[n])] or len(started) == 1
    assert journal.index.runs(limit=5), "a late run is still a run, and shows in Settings"


async def test_one_at_a_time(journal: Journal, provider) -> None:
    """A fortnight away makes all three overdue at once. Running them together
    would spend three jobs' worth of model calls in the first minute of a
    session, and they are already a day late — another quarter hour is nothing.
    """
    assert len(await catch_up(journal, provider)) == 1


async def test_running_it_stops_it_being_overdue(journal: Journal, provider) -> None:
    """The loop that would otherwise never close: a run writes a row, and the
    row is what this reads."""
    [name] = await catch_up(journal, provider)

    assert name not in due(journal)


async def test_a_job_that_fails_is_not_retried_every_quarter_hour(
    journal: Journal, provider, monkeypatch
) -> None:
    """`run_job` records the failure before re-raising, and that row resets the
    clock. Otherwise a job failing for an unrelated reason becomes a model call
    every fifteen minutes for as long as the app is open."""

    async def boom(*_args, **_kwargs):
        raise RuntimeError("upstream is down")

    monkeypatch.setitem(overdue.PERIODS, "scout", timedelta(days=1))
    from tilt.jobs import runner

    monkeypatch.setitem(runner.JOBS, "scout", boom)
    ran(journal.index, "themes", ago=timedelta(minutes=1))
    ran(journal.index, "week", ago=timedelta(minutes=1))

    assert await catch_up(journal, provider) == ["scout"]

    assert "scout" not in due(journal)


# ----------------------------------------------------------------- the record


def test_the_last_run_is_the_most_recent_one(journal: Journal) -> None:
    ran(journal.index, "scout", ago=timedelta(days=9))
    ran(journal.index, "scout", ago=timedelta(minutes=2))

    last = journal.index.last_run("scout")

    assert last is not None and utcnow() - last < timedelta(minutes=5)


def test_a_job_never_run_has_no_last_run(journal: Journal) -> None:
    assert journal.index.last_run("scout") is None


def test_a_failed_run_still_counts_as_a_run(journal: Journal) -> None:
    """A job failing daily is a different problem from one never reached, and
    conflating them turns the first into a model call every fifteen minutes."""
    when = utcnow() - timedelta(minutes=1)
    journal.index.record_run(
        AgentRun(
            id=new_id(), job="scout", model="echo", status="error", started=when, error="nope"
        )
    )

    assert "scout" not in due(journal)


@pytest.mark.parametrize("name", sorted(PERIODS))
def test_every_watched_job_is_one_the_runner_knows(name: str) -> None:
    """A typo here would be silent: an unknown name is simply never due."""
    from tilt.jobs.runner import JOBS

    assert name in JOBS
