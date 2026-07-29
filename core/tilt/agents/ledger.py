"""Cost accounting.

Every model call is wrapped so spend is observable rather than a surprise at
the end of the month, and so a runaway scheduled job cannot quietly drain a
budget. User-initiated calls are always allowed through; only unattended work
is gated, because blocking someone from their own journal to save four cents is
the wrong trade.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tilt.agents.base import AgentError, AgentProvider, Completion, Reference
from tilt.models import AgentRun, utcnow
from tilt.store.files import new_id
from tilt.store.index import Index

SCHEDULED_BUDGET_FRACTION = 0.8
"""Unattended jobs stop here, leaving headroom for interactive use."""


class BudgetExceeded(AgentError):
    pass


def month_start(now: datetime | None = None) -> str:
    now = now or utcnow()
    return now.astimezone(UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()


class MeteredProvider:
    """Wraps a provider so each call is priced and recorded."""

    def __init__(self, provider: AgentProvider, index: Index, ceiling_usd: float) -> None:
        self._provider = provider
        self._index = index
        self._ceiling = ceiling_usd

    @property
    def name(self) -> str:
        return self._provider.name

    @property
    def follows_references(self) -> bool:
        return getattr(self._provider, "follows_references", False)

    def spend_this_month(self) -> float:
        return self._index.spend_since(month_start())

    def _check_budget(self, interactive: bool) -> None:
        if interactive or self._ceiling <= 0:
            return
        if self.spend_this_month() >= self._ceiling * SCHEDULED_BUDGET_FRACTION:
            raise BudgetExceeded(
                "Scheduled agent work is paused: this month's spend has reached "
                f"{SCHEDULED_BUDGET_FRACTION:.0%} of the ${self._ceiling:.2f} ceiling."
            )

    async def complete(
        self,
        prompt: str,
        *,
        job: str,
        system: str | None = None,
        interactive: bool = True,
        reference: Reference | None = None,
    ) -> Completion:
        self._check_budget(interactive)

        run = AgentRun(
            id=new_id(),
            job=job,
            model=getattr(self._provider, "name", "unknown"),
            status="running",
            started=utcnow(),
        )
        try:
            # Only passed when there is one. `follows_references` is what the
            # caller checks before setting it, so a provider that cannot take
            # the argument is never handed it — and a plain provider stays a
            # two-argument function.
            extra = {"reference": reference} if reference is not None else {}
            completion = await self._provider.complete(prompt, system=system, **extra)
        except Exception as exc:
            run.status = "error"
            run.finished = utcnow()
            run.error = str(exc)[:500]
            self._index.record_run(run)
            raise

        run.model = completion.model
        run.status = "ok"
        run.finished = utcnow()
        run.tokens_in = completion.tokens_in
        run.tokens_out = completion.tokens_out
        run.cost_usd = self._provider.pricing.cost(completion.tokens_in, completion.tokens_out)
        self._index.record_run(run)
        return completion
