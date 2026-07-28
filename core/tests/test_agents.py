from __future__ import annotations

import pytest

from tilt.agents import build_provider
from tilt.agents.base import AgentError, Pricing
from tilt.agents.echo import EchoProvider
from tilt.agents.ledger import BudgetExceeded, MeteredProvider
from tilt.agents.reflect import build_prompt, reflect_on
from tilt.config import Settings
from tilt.journal import Journal
from tilt.models import EntryCreate, EntryKind, ReplyKind, utcnow
from tilt.store.index import Index


class FailingProvider:
    name = "failing"
    pricing = Pricing(1.0, 1.0)

    async def complete(self, prompt: str, *, system: str | None = None):
        raise AgentError("upstream is down")


class CountingProvider:
    name = "counting"
    pricing = Pricing(input_per_m=1.50, output_per_m=7.50)

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, prompt: str, *, system: str | None = None):
        from tilt.agents.base import Completion

        self.calls += 1
        return Completion(text="ok", model="test", tokens_in=1_000_000, tokens_out=1_000_000)


# ----------------------------------------------------------------- providers


def test_auto_provider_falls_back_to_offline_without_a_key() -> None:
    assert isinstance(build_provider(Settings(provider="auto", gemini_api_key=None)), EchoProvider)


def test_explicit_gemini_without_a_key_is_an_error() -> None:
    with pytest.raises(AgentError, match="requires TILT_GEMINI_API_KEY"):
        build_provider(Settings(provider="gemini", gemini_api_key=None))


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(AgentError, match="Unknown provider"):
        build_provider(Settings(provider="nonsense"))


async def test_echo_provider_is_grounded_in_the_prompt() -> None:
    prompt = "ENTRY:\nAttention behaves like a filter rather than a spotlight."
    result = await EchoProvider().complete(prompt)

    assert "attention" in result.text.lower()
    assert "is offline" in result.text.lower(), "must never pass as a real model"
    assert result.tokens_in > 0


async def test_echo_provider_signs_with_the_configured_agent_name() -> None:
    """Offline mode cannot embody a personality, but renaming the agent must
    still be visibly real before a key is added."""
    result = await EchoProvider().complete(
        "ENTRY:\nA thought.", system='Your name is "Neo".\n\nYour manner: terse.'
    )
    assert "Neo is offline" in result.text


async def test_echo_provider_is_deterministic() -> None:
    prompt = "ENTRY:\nThe same input every time."
    first = await EchoProvider().complete(prompt)
    second = await EchoProvider().complete(prompt)
    assert first.text == second.text


# -------------------------------------------------------------------- ledger


async def test_metered_provider_records_cost(index: Index) -> None:
    metered = MeteredProvider(CountingProvider(), index, ceiling_usd=100.0)
    await metered.complete("hello", job="test")

    runs = index.runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"
    # 1M in at $1.50 + 1M out at $7.50
    assert runs[0]["cost_usd"] == pytest.approx(9.0)
    assert metered.spend_this_month() == pytest.approx(9.0)


async def test_failed_calls_are_recorded_then_raised(index: Index) -> None:
    metered = MeteredProvider(FailingProvider(), index, ceiling_usd=100.0)

    with pytest.raises(AgentError, match="upstream is down"):
        await metered.complete("hello", job="test")

    runs = index.runs()
    assert runs[0]["status"] == "error"
    assert "upstream is down" in runs[0]["error"]


async def test_scheduled_work_stops_at_the_budget_but_interactive_does_not(index: Index) -> None:
    inner = CountingProvider()
    metered = MeteredProvider(inner, index, ceiling_usd=10.0)

    await metered.complete("first", job="test", interactive=False)  # spends $9, over 80% of $10

    with pytest.raises(BudgetExceeded):
        await metered.complete("second", job="test", interactive=False)

    await metered.complete("third", job="test", interactive=True)
    assert inner.calls == 2, "the user must never be locked out of their own journal"


# ------------------------------------------------------------------- reflect


def test_prompt_includes_entry_and_context(journal: Journal) -> None:
    entry = journal.create(EntryCreate(body="Attention is a filter."))
    other = journal.create(EntryCreate(body="Filters discard, spotlights select."))

    prompt = build_prompt(journal.get(entry.id), [journal.get(other.id)])
    assert "ENTRY:" in prompt
    assert "EARLIER ENTRIES:" in prompt
    assert "Attention is a filter." in prompt


def test_prompt_omits_context_section_when_empty(journal: Journal) -> None:
    entry = journal.create(EntryCreate(body="A first thought, with nothing before it."))
    assert "EARLIER ENTRIES" not in build_prompt(journal.get(entry.id), [])


async def test_reflect_threads_a_reply_under_the_entry(
    journal: Journal, provider: MeteredProvider
) -> None:
    entry = journal.create(EntryCreate(body="Attention behaves like a filter, not a spotlight."))
    reply = await reflect_on(journal, provider, entry.id)

    assert reply is not None
    assert reply.kind is EntryKind.REPLY
    assert reply.reply_kind is ReplyKind.REFLECTION
    assert reply.parent == entry.id

    thread = journal.thread(entry.id)
    assert [r.id for r in thread.replies] == [reply.id]


async def test_reflect_on_missing_entry_returns_none(
    journal: Journal, provider: MeteredProvider
) -> None:
    assert await reflect_on(journal, provider, "does-not-exist") is None


async def test_reply_survives_an_index_rebuild(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Machine replies are real Markdown files, not database rows."""
    entry = journal.create(EntryCreate(body="Something worth reflecting on at length."))
    reply = await reflect_on(journal, provider, entry.id)

    journal.rebuild()
    thread = journal.thread(entry.id)
    assert [r.id for r in thread.replies] == [reply.id]


def test_month_start_is_first_of_month() -> None:
    from tilt.agents.ledger import month_start

    assert month_start(utcnow()).startswith(f"{utcnow():%Y-%m}-01T00:00:00")
