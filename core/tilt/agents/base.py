"""Agent provider contract.

Everything that talks to a model goes through :class:`AgentProvider`. Keeping
this surface tiny is what lets the test suite run with no network and no key,
and what will let a local MLX provider slot in beside the hosted one later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class AgentError(RuntimeError):
    """Raised when a provider cannot produce a completion."""


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens."""

    input_per_m: float
    output_per_m: float

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in / 1_000_000) * self.input_per_m + (
            tokens_out / 1_000_000
        ) * self.output_per_m


@runtime_checkable
class AgentProvider(Protocol):
    name: str
    pricing: Pricing

    async def complete(self, prompt: str, *, system: str | None = None) -> Completion: ...


def estimate_tokens(text: str) -> int:
    """Rough token count for providers that do not report usage.

    Four characters per token is the standard approximation for English prose;
    it is only used to keep the cost ledger from showing zero.
    """
    return max(1, len(text) // 4)
