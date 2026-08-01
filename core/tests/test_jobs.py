"""The unattended half of the agent layer.

The behaviour these protect is the one nobody watches happen: what Tilt does to
a journal while its window is closed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tilt.agents.base import AgentError, Completion, Pricing
from tilt.agents.echo import EchoProvider
from tilt.agents.ledger import MeteredProvider
from tilt.config import Settings
from tilt.jobs.runner import JOBS, run_job
from tilt.jobs.scheduler import Schedule
from tilt.jobs.sweep import sweep
from tilt.jobs.themes import (
    apply_merge,
    candidates,
    keep_themes,
    survivor,
    tokens,
)
from tilt.journal import Journal
from tilt.models import Entry, Theme, ThemeStatus, utcnow
from tilt.store import files
from tilt.store.index import Index


def written(journal: Journal, body: str, *, age: timedelta = timedelta(hours=1)) -> Entry:
    """An entry that exists but no agent has ever seen.

    This is exactly what ⌥Space produces: the capture window saves a thought and
    closes, and nothing files it. Backdated so the sweep's quiet period does not
    hold it back.
    """
    when = utcnow() - age
    entry = Entry(id=files.new_id(), created=when, updated=when, body=body)
    journal.index.upsert(entry, files.write(entry, journal.entries_root))
    return entry


def theme_at(index: Index, journal: Journal, label: str, *, age: timedelta) -> Theme:
    """A theme whose most recent member was written ``age`` ago."""
    now = utcnow()
    theme = index.upsert_theme(Theme(id=files.new_id(), label=label, created=now, updated=now))
    entry = written(journal, f"a thought about {label}", age=age)
    index.set_entry_themes(entry.id, [theme.id])
    journal.set_themes(entry.id, [theme.label])
    return index.get_theme(theme.id)


class Failing:
    name = "failing"
    pricing = Pricing(1.0, 1.0)

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, prompt: str, *, system: str | None = None):
        self.calls += 1
        raise AgentError("upstream is down")


class Scripted:
    """Returns whatever it is told to, so a merge can be provoked on demand."""

    name = "scripted"
    pricing = Pricing(0.0, 0.0)

    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    async def complete(self, prompt: str, *, system: str | None = None):
        self.prompts.append(prompt)
        return Completion(text=self.text, model="scripted", tokens_in=1, tokens_out=1)


# --------------------------------------------------------------------- sweep


async def test_sweep_files_an_entry_nothing_ever_looked_at(
    journal: Journal, provider: MeteredProvider
) -> None:
    entry = written(journal, "Attention behaves like a filter, not a spotlight.")
    assert journal.index.themes_for([entry.id])[entry.id] == []

    summary = await sweep(journal, provider)

    assert summary.considered == 1
    assert summary.filed == 1
    assert journal.index.themes_for([entry.id])[entry.id] != [], "should now be in a folder"


async def test_sweep_leaves_a_just_written_entry_alone(
    journal: Journal, provider: MeteredProvider
) -> None:
    """The interface is already filing it. Racing that pays twice for one answer."""
    written(journal, "Just typed this.", age=timedelta(seconds=1))

    assert (await sweep(journal, provider)).considered == 0


async def test_sweep_does_not_reconsider_what_it_has_already_done(
    journal: Journal, provider: MeteredProvider
) -> None:
    written(journal, "Attention behaves like a filter, not a spotlight.")

    first = await sweep(journal, provider)
    second = await sweep(journal, provider)

    assert first.considered == 1
    assert second.considered == 0, "a second pass over settled entries is pure spend"


async def test_an_entry_with_no_connections_is_still_settled(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Finding nothing is a result, not an absence of one.

    Without recording it, every unconnected thought looks unexamined and the
    nightly sweep judges the whole journal again for as long as it exists.
    """
    entry = written(journal, "Something entirely on its own.")

    await sweep(journal, provider)

    assert journal.index.links_for([entry.id])[entry.id] == []
    assert journal.index.backlog(limit=10, settled_before=utcnow().isoformat()) == []


async def test_settled_work_is_recovered_when_the_index_is_thrown_away(
    journal: Journal, provider: MeteredProvider
) -> None:
    """index.db is documented as a disposable cache. Deleting it must not
    hand the agent a bill for work it already did.

    Themes and links come back from each entry's frontmatter, so a rebuilt
    journal that still looked unexamined would re-file and re-judge everything
    in it — at full price, for answers already on disk.
    """
    written(journal, "Attention behaves like a filter, not a spotlight.")
    written(journal, "A spotlight metaphor for attention explains too little.")
    await sweep(journal, provider)

    journal.index._conn.execute("DELETE FROM entry_state")
    journal.index._conn.commit()
    journal.rebuild()

    assert (await sweep(journal, provider)).considered == 0


async def test_sweep_is_bounded(journal: Journal, provider: MeteredProvider) -> None:
    """A first run against an imported journal must not fire a call per entry."""
    for i in range(8):
        written(journal, f"Thought number {i} about attention and memory.")

    assert (await sweep(journal, provider, batch=3)).considered == 3


async def test_sweep_stops_at_the_spending_ceiling_without_failing(
    journal: Journal, index: Index
) -> None:
    """The ceiling pausing unattended work is a normal outcome, not a fault.

    The backlog survives, so the next pass resumes at the same place.
    """

    class Expensive:
        name = "expensive"
        pricing = Pricing(input_per_m=1000.0, output_per_m=1000.0)

        async def complete(self, prompt: str, *, system: str | None = None):
            return Completion(text="{}", model="x", tokens_in=1_000_000, tokens_out=1_000_000)

    metered = MeteredProvider(Expensive(), index, ceiling_usd=1.0)
    for i in range(4):
        written(journal, f"Thought {i}.")

    summary = await sweep(journal, metered)

    assert summary.paused
    assert summary.filed < 4
    assert index.backlog(limit=10, settled_before=utcnow().isoformat()), "backlog must remain"


async def test_sweep_gives_up_on_a_provider_that_is_down(
    journal: Journal, index: Index
) -> None:
    """One bad entry should not stop the pass; a dead provider should."""
    for i in range(6):
        written(journal, f"Thought {i}.")
    failing = Failing()

    summary = await sweep(journal, MeteredProvider(failing, index, ceiling_usd=100.0))

    assert summary.filed == 0
    assert failing.calls == 2, "two strikes, not one call per entry in the backlog"


# --------------------------------------------------------------- theme-keeper


def test_merge_candidates_are_names_of_one_subject() -> None:
    now = utcnow()

    def theme(label: str, **kw) -> Theme:
        return Theme(id=label, label=label, created=now, updated=now, **kw)

    pairs = candidates(
        [theme("Attention"), theme("Attention Economy"), theme("Deep Work"), theme("Deep Learning")]
    )
    labels = {frozenset((a.label, b.label)) for a, b in pairs}

    assert frozenset(("Attention", "Attention Economy")) in labels
    assert frozenset(("Deep Work", "Deep Learning")) not in labels, (
        "a shared adjective is not a shared subject"
    )


def test_two_hand_named_folders_are_never_proposed_for_merging() -> None:
    now = utcnow()
    a = Theme(id="a", label="Attention", created=now, updated=now, pinned_label=True)
    b = Theme(id="b", label="Attention Economy", created=now, updated=now, pinned_label=True)

    assert candidates([a, b]) == [], "two deliberate names are two deliberate distinctions"


def test_tokens_ignore_joining_words() -> None:
    assert tokens("Memory and the Self") == {"memory", "self"}


def test_a_pinned_name_survives_a_merge_whatever_the_model_prefers() -> None:
    now = utcnow()
    mine = Theme(id="a", label="Focus", created=now, updated=now, pinned_label=True, count=1)
    theirs = Theme(id="b", label="Focus And Attention", created=now, updated=now, count=9)

    keep, drop = survivor(mine, theirs, choice="Focus And Attention")

    assert keep.id == mine.id, "renaming a folder is an instruction, not a suggestion"
    assert drop.id == theirs.id


def test_an_unrecognised_choice_falls_back_to_the_larger_folder() -> None:
    now = utcnow()
    small = Theme(id="a", label="Focus", created=now, updated=now, count=1)
    large = Theme(id="b", label="Attention", created=now, updated=now, count=9)

    keep, _ = survivor(small, large, choice="Something Else Entirely")

    assert keep.id == large.id


async def test_a_theme_nobody_has_added_to_goes_dormant(
    journal: Journal, index: Index, provider: MeteredProvider
) -> None:
    stale = theme_at(index, journal, "Old Preoccupation", age=timedelta(days=200))
    live = theme_at(index, journal, "Current Question", age=timedelta(days=2))

    await keep_themes(journal, provider)

    assert index.get_theme(stale.id).status is ThemeStatus.DORMANT
    assert index.get_theme(live.id).status is ThemeStatus.ACTIVE


async def test_a_dormant_theme_wakes_when_something_new_lands_in_it(
    journal: Journal, index: Index, provider: MeteredProvider
) -> None:
    stale = theme_at(index, journal, "Old Preoccupation", age=timedelta(days=200))
    await keep_themes(journal, provider)
    assert index.get_theme(stale.id).status is ThemeStatus.DORMANT

    now = utcnow()
    index.upsert_theme(
        Theme(id=files.new_id(), label="Old Preoccupation", created=now, updated=now)
    )

    assert index.get_theme(stale.id).status is ThemeStatus.ACTIVE


async def test_dormant_themes_sort_after_live_ones(
    journal: Journal, index: Index, provider: MeteredProvider
) -> None:
    """Dormant, not deleted. A subject you set down is part of the record."""
    theme_at(index, journal, "Old Preoccupation", age=timedelta(days=200))
    theme_at(index, journal, "Current Question", age=timedelta(days=2))

    await keep_themes(journal, provider)

    assert [t.label for t in index.themes()] == ["Current Question", "Old Preoccupation"]


async def test_a_merge_survives_rebuilding_the_index_from_disk(
    journal: Journal, index: Index
) -> None:
    """The load-bearing one.

    Themes are restored from each entry's own Markdown on boot. A merge that
    touched only SQLite would look right until the next restart, then bring the
    folder it deleted straight back.
    """
    keep = theme_at(index, journal, "Attention", age=timedelta(days=1))
    drop = theme_at(index, journal, "Attention Economy", age=timedelta(days=1))

    metered = MeteredProvider(Scripted('{"merges": [{"n": 1, "keep": "Attention"}]}'), index, 100.0)
    summary = await keep_themes(journal, metered)

    assert summary.merged == 1
    assert [t.label for t in index.themes()] == ["Attention"]

    journal.rebuild()

    assert [t.label for t in index.themes()] == ["Attention"], (
        "the dropped folder came back from stale frontmatter"
    )
    assert index.get_theme(keep.id).count == 2, "both entries should have moved across"
    assert index.get_theme(drop.id) is None


async def test_merging_moves_the_entries_rather_than_copying_them(
    journal: Journal, index: Index
) -> None:
    keep = theme_at(index, journal, "Memory", age=timedelta(days=1))
    drop = theme_at(index, journal, "Memory And Recall", age=timedelta(days=1))
    moved = index.entries_in_theme(drop.id)

    apply_merge(journal, keep, drop)

    for entry in moved:
        labels = [t.label for t in index.themes_for([entry.id])[entry.id]]
        assert labels == ["Memory"], "an entry must not end up in both halves of a merge"


async def test_offline_never_merges_two_folders(
    journal: Journal, index: Index, provider: MeteredProvider
) -> None:
    """Keyword overlap is what nominated the pair; it has no opinion left about
    whether they are one subject, and a merge cannot be undone from the UI."""
    theme_at(index, journal, "Attention", age=timedelta(days=1))
    theme_at(index, journal, "Attention Economy", age=timedelta(days=1))

    summary = await keep_themes(journal, provider)

    assert summary.merged == 0
    assert len(index.themes()) == 2


async def test_the_keeper_removes_folders_with_nothing_in_them(
    journal: Journal, index: Index, provider: MeteredProvider
) -> None:
    now = utcnow()
    index.upsert_theme(Theme(id=files.new_id(), label="Empty", created=now, updated=now))

    await keep_themes(journal, provider)

    assert index.themes() == []


# --------------------------------------------------------------------- runner


async def test_a_job_records_what_it_did(journal: Journal, provider: MeteredProvider) -> None:
    """A job that finished and says nothing is indistinguishable from one that
    silently stopped working."""
    written(journal, "Attention behaves like a filter, not a spotlight.")

    await run_job("sweep", journal, provider)

    row = next(r for r in journal.index.runs() if r["job"] == "sweep")
    assert row["status"] == "ok"
    assert "filed" in row["detail"]
    assert row["finished"] is not None


async def test_a_job_that_fails_still_leaves_a_record(
    journal: Journal, index: Index, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setitem(JOBS, "sweep", explode)
    metered = MeteredProvider(EchoProvider(), index, ceiling_usd=1.0)

    with pytest.raises(RuntimeError):
        await run_job("sweep", journal, metered)

    row = next(r for r in index.runs() if r["job"] == "sweep")
    assert row["status"] == "error"
    assert "boom" in row["error"]


async def test_a_paused_job_is_not_recorded_as_a_failure(
    journal: Journal, index: Index
) -> None:
    class Expensive:
        name = "expensive"
        pricing = Pricing(input_per_m=1000.0, output_per_m=1000.0)

        async def complete(self, prompt: str, *, system: str | None = None):
            return Completion(text="{}", model="x", tokens_in=1_000_000, tokens_out=1_000_000)

    for i in range(3):
        written(journal, f"Thought {i}.")

    await run_job("sweep", journal, MeteredProvider(Expensive(), index, ceiling_usd=1.0))

    row = next(r for r in index.runs() if r["job"] == "sweep")
    assert row["status"] == "paused", "the ceiling working is not the job breaking"


async def test_an_unknown_job_is_a_key_error(
    journal: Journal, provider: MeteredProvider
) -> None:
    with pytest.raises(KeyError):
        await run_job("nonsense", journal, provider)

    assert journal.index.runs() == [], "a job that never existed did not run"


# ------------------------------------------------------------------ schedule


async def test_the_schedule_can_be_started_and_stopped(
    journal: Journal, provider: MeteredProvider, settings: Settings
) -> None:
    # Async because APScheduler's asyncio scheduler binds to the running loop
    # when it starts — the same reason the real one starts inside the lifespan
    # rather than at import time.
    schedule = Schedule(journal, provider, settings)
    schedule.start()
    try:
        assert schedule._scheduler is not None
        jobs = {job.id for job in schedule._scheduler.get_jobs()}
        assert jobs == {"sweep", "themes", "vectors", "scout", "week"}
    finally:
        schedule.shutdown()

    assert schedule._scheduler is None


async def test_starting_twice_does_not_double_the_jobs(
    journal: Journal, provider: MeteredProvider, settings: Settings
) -> None:
    """The lifespan runs once, but a restart in the same process must not stack
    two sweeps on the same interval."""
    schedule = Schedule(journal, provider, settings)
    schedule.start()
    schedule.start()
    try:
        assert len(schedule._scheduler.get_jobs()) == 5
    finally:
        schedule.shutdown()


# ------------------------------------------------------------------ migration


def test_an_index_from_an_earlier_version_gains_the_new_columns(tmp_path) -> None:
    """Rebuilding the whole index instead would discard every folder name the
    user has pinned, which lives nowhere else."""
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE themes (
            id TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL, updated TEXT NOT NULL,
            pinned_label INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO themes VALUES ('t1', 'My Name For It', '', '2026-01-01', '2026-01-01', 1);
        CREATE TABLE agent_runs (
            id TEXT PRIMARY KEY, job TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
            started TEXT NOT NULL, finished TEXT, tokens_in INTEGER NOT NULL DEFAULT 0,
            tokens_out INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0.0, error TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    index = Index(path)
    try:
        theme = index.get_theme("t1")
        assert theme.label == "My Name For It"
        assert theme.pinned_label is True
        assert theme.status is ThemeStatus.ACTIVE
    finally:
        index.close()


# ----------------------------------------------------------------------- api


def test_a_job_can_be_triggered_by_hand(client) -> None:
    """Waiting until 3am to find out whether a job works is not a way to build
    one."""
    client.post("/entries", json={"body": "Attention is a filter, not a spotlight."})

    response = client.post("/agent/jobs/sweep")

    assert response.status_code == 200
    assert response.json()["job"] == "sweep"


def test_an_unknown_job_is_rejected(client) -> None:
    assert client.post("/agent/jobs/nonsense").status_code == 404


def test_activity_reports_what_happened_while_you_were_away(client) -> None:
    before = utcnow().isoformat()
    created = client.post("/entries", json={"body": "Attention is a filter."}).json()
    client.post("/agent/process", json={"entry_id": created["entry"]["id"]})

    activity = client.get("/agent/activity", params={"since": before}).json()

    assert activity["filed"] == 1


def test_activity_since_now_is_empty(client, journal: Journal) -> None:
    client.post("/entries", json={"body": "Attention is a filter."})

    activity = client.get("/agent/activity", params={"since": utcnow().isoformat()}).json()

    assert activity == {"since": activity["since"], "filed": 0, "connected": 0}
