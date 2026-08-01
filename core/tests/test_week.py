"""The weekly look back, and mostly its silence.

The failure mode of a weekly review is not that it says the wrong thing. It is
that it says something every week, including the weeks that held nothing, until
nobody reads it and the one week that mattered goes past with the rest. So the
first tests here are about the pass finding nothing and reporting nothing, and
about the fact that it cannot spend money to reach that answer.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta

import pytest

from tilt.agents.base import Completion, Pricing
from tilt.agents.ledger import MeteredProvider
from tilt.jobs.week import SETTLED, look_back
from tilt.journal import Journal
from tilt.models import (
    Entry,
    EntryKind,
    Link,
    LinkKind,
    Notice,
    Provenance,
    ReplyKind,
    utcnow,
)
from tilt.store import files
from tilt.store.index import Index, content_hash
from tilt.store.vectors import VectorStore

DIMS = 16


class Counting:
    """A provider that would answer, and records that it was never asked."""

    name = "counting"
    pricing = Pricing(1.0, 1.0)

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, prompt: str, *, system: str | None = None):
        self.calls += 1
        return Completion(text="{}", model="counting", tokens_in=1, tokens_out=1)


class Placed:
    signature = "test/placed/16"
    dims = DIMS

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - unused
        raise AssertionError("the weekly pass must never embed anything")


def unit(rng: random.Random) -> list[float]:
    raw = [rng.gauss(0, 1) for _ in range(DIMS)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def near(rng: random.Random, centre: list[float]) -> list[float]:
    raw = [c + 0.05 * rng.gauss(0, 1) for c in centre]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


class Week:
    def __init__(self, tmp_path) -> None:
        self.index = Index(tmp_path / "index.db")
        self.vectors = VectorStore(tmp_path / "vectors.db")
        self.embedder = Placed()
        self.journal = Journal(tmp_path / "journal", self.index, self.vectors, self.embedder)
        self.provider_impl = Counting()
        self.provider = MeteredProvider(self.provider_impl, self.index, ceiling_usd=1.0)
        self.rng = random.Random(29)

    def wrote(
        self,
        body: str,
        *,
        age: timedelta = timedelta(days=1),
        kind: EntryKind = EntryKind.NOTE,
        reply_kind: ReplyKind | None = None,
        at: list[float] | None = None,
    ) -> Entry:
        when = utcnow() - age
        entry = Entry(
            id=files.new_id(),
            created=when,
            updated=when,
            kind=kind,
            reply_kind=reply_kind,
            provenance=Provenance.SELF,
            body=body,
        )
        self.index.upsert(entry, files.write(entry, self.journal.entries_root))
        if at is not None:
            self.vectors.put(entry.id, self.embedder.signature, content_hash(body), at)
        return entry

    def linked(self, a: Entry, b: Entry, kind: LinkKind, *, age: timedelta) -> Link:
        link = Link(
            id=files.new_id(),
            src_id=a.id,
            dst_id=b.id,
            kind=kind,
            rationale="judged earlier, and paid for then",
            created=utcnow() - age,
        )
        self.index.add_link(link)
        return link

    def close(self) -> None:
        self.vectors.close()
        self.index.close()


@pytest.fixture
def week(tmp_path):
    w = Week(tmp_path)
    yield w
    w.close()


# ------------------------------------------------------------------- silence


async def test_a_quiet_week_says_nothing(week: Week) -> None:
    week.wrote("Wrote a bit about attention today.")
    week.wrote("And a bit more.", age=timedelta(days=3))

    summary = await look_back(week.journal, week.provider)

    assert summary.proposed == 0
    assert week.index.open_notices() == []
    assert "Nothing this week" in summary.detail


async def test_it_cannot_spend_anything(week: Week) -> None:
    """The reason an unattended weekly pass is defensible at all. Noticing is
    two queries; the synthesis is a button."""
    a = week.wrote("Attention is a filter.", age=timedelta(days=2))
    b = week.wrote("Attention is a spotlight.", age=timedelta(days=1))
    week.linked(a, b, LinkKind.CONTRADICTION, age=timedelta(days=1))

    await look_back(week.journal, week.provider)

    assert week.provider_impl.calls == 0
    assert week.provider.spend_this_month() == 0.0


# ------------------------------------------------------------ contradictions


async def test_disagreeing_with_yourself_is_worth_saying(week: Week) -> None:
    """The one link kind reserved for two things you wrote. Its existence is the
    finding — the connector already judged it and already paid for it."""
    a = week.wrote("Attention is a filter that discards.", age=timedelta(days=4))
    b = week.wrote("Attention is a spotlight that selects.", age=timedelta(days=1))
    week.linked(a, b, LinkKind.CONTRADICTION, age=timedelta(days=1))

    summary = await look_back(week.journal, week.provider)

    [notice] = week.index.open_notices()
    assert notice.kind == "contradiction"
    assert set(notice.entry_ids) == {a.id, b.id}
    assert summary.proposed == 1


async def test_an_old_contradiction_is_not_this_week_s_news(week: Week) -> None:
    """Ages are absolute rather than expressed against WINDOW: a fixture that
    moves with the constant it is checking cannot check it."""
    a = week.wrote("Attention is a filter.", age=timedelta(days=90))
    b = week.wrote("Attention is a spotlight.", age=timedelta(days=80))
    week.linked(a, b, LinkKind.CONTRADICTION, age=timedelta(days=30))

    await look_back(week.journal, week.provider)

    assert week.index.open_notices() == []


async def test_reading_something_you_disagree_with_is_not_a_contradiction(week: Week) -> None:
    """`counterpoint` exists precisely so that holding two opposed views at
    once is not logged as changing your mind."""
    a = week.wrote("Attention is a filter.", age=timedelta(days=2))
    b = week.wrote("A paper arguing the opposite.", age=timedelta(days=1))
    week.linked(a, b, LinkKind.COUNTERPOINT, age=timedelta(days=1))

    await look_back(week.journal, week.provider)

    assert week.index.open_notices() == []


async def test_the_same_finding_is_never_raised_twice(week: Week) -> None:
    """It will be just as true next Sunday, and just as true the Sunday after."""
    a = week.wrote("Attention is a filter.", age=timedelta(days=2))
    b = week.wrote("Attention is a spotlight.", age=timedelta(days=1))
    week.linked(a, b, LinkKind.CONTRADICTION, age=timedelta(days=1))

    first = await look_back(week.journal, week.provider)
    second = await look_back(week.journal, week.provider)

    assert first.proposed == 1
    assert second.proposed == 0
    assert len(week.index.open_notices()) == 1


# -------------------------------------------------------- returning questions


def question_and_return(week: Week, *, question_age: timedelta, answer_age: timedelta):
    where = unit(week.rng)
    question = week.wrote(
        "What is it that makes some interruptions cost nothing?",
        age=question_age,
        kind=EntryKind.CARD,
        reply_kind=ReplyKind.QUESTION,
        at=near(week.rng, where),
    )
    answer = week.wrote(
        "Some interruptions cost nothing because you were already stopping.",
        age=answer_age,
        at=near(week.rng, where),
    )
    return question, answer


async def test_an_old_question_you_came_back_to(week: Week) -> None:
    """Found by meaning rather than by words: a question and the entry that
    circles it months later rarely share vocabulary, which is the whole reason
    this is measured against vectors."""
    question, answer = question_and_return(
        week, question_age=SETTLED + timedelta(days=30), answer_age=timedelta(days=2)
    )

    await look_back(week.journal, week.provider)

    [notice] = week.index.open_notices()
    assert notice.kind == "question"
    assert set(notice.entry_ids) == {question.id, answer.id}


async def test_a_question_asked_this_month_is_a_train_of_thought(week: Week) -> None:
    """Not a return. Circling something you asked on Tuesday is how thinking
    works, and reporting it back would be telling you what you just did."""
    question_and_return(
        week, question_age=timedelta(days=5), answer_age=timedelta(days=1)
    )

    await look_back(week.journal, week.provider)

    assert week.index.open_notices() == []


async def test_an_old_question_nobody_went_near_stays_quiet(week: Week) -> None:
    week.wrote(
        "What is it that makes some interruptions cost nothing?",
        age=SETTLED + timedelta(days=30),
        kind=EntryKind.CARD,
        reply_kind=ReplyKind.QUESTION,
        at=unit(week.rng),
    )
    week.wrote("Sourdough wants a wetter feed in winter.", at=unit(week.rng))

    await look_back(week.journal, week.provider)

    assert week.index.open_notices() == []


async def test_without_vectors_that_half_is_simply_absent(tmp_path) -> None:
    """No key, no returning questions — and no error, and no fallback to shared
    words that would find the wrong thing and call it the same finding."""
    index = Index(tmp_path / "index.db")
    journal = Journal(tmp_path / "journal", index)
    provider = MeteredProvider(Counting(), index, ceiling_usd=1.0)
    try:
        summary = await look_back(journal, provider)
        assert summary.proposed == 0
        assert index.open_notices() == []
    finally:
        index.close()


# ------------------------------------------------------------- over the wire


def test_the_notice_routes_carry_it(client) -> None:
    """Including the empty case, which is what the interface sees most weeks."""
    assert client.get("/agent/notices").json() == []
    assert client.delete("/agent/notices/nope").status_code == 404
    assert client.post("/agent/notices/nope/reflect").status_code == 404


def test_the_week_is_a_job_you_can_run_by_hand(client) -> None:
    summary = client.post("/agent/jobs/week").json()

    assert summary["job"] == "week"
    assert summary["proposed"] == 0


def test_synthesising_answers_the_notice_and_puts_it_away(client) -> None:
    """The only part that spends, and it happens because somebody asked. The
    answer arrives threaded under the entry, where machine replies already live
    — not in a weekly digest with its own place to be read."""
    index = client.app.state.journal.index
    first = client.post("/entries", json={"body": "Attention is a filter."}).json()["entry"]
    second = client.post("/entries", json={"body": "Attention is a spotlight."}).json()["entry"]
    index.add_notice(
        Notice(
            id=files.new_id(),
            kind="contradiction",
            body="You wrote two things that pull against each other.",
            entry_ids=[first["id"], second["id"]],
            subject="link:planted",
            created=utcnow(),
        )
    )

    reply = client.post(f"/agent/notices/{index.open_notices()[0].id}/reflect").json()

    assert reply["kind"] == "reply"
    assert reply["parent"] == second["id"], "threaded under the more recent of the two"
    assert index.open_notices() == [], "answered, so it should not still be asking"
