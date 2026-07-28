"""Agent layer: providers, metering, and the jobs built on top of them."""

from __future__ import annotations

from tilt.agents.base import AgentError, AgentProvider, Completion, Pricing
from tilt.agents.echo import EchoProvider
from tilt.agents.ledger import BudgetExceeded, MeteredProvider
from tilt.config import Settings


def build_provider(settings: Settings) -> AgentProvider:
    """Choose a provider from configuration.

    ``auto`` resolves to Gemini when a key is present and the offline provider
    otherwise, so a fresh clone runs end to end with no setup.
    """
    choice = settings.provider.lower()
    if choice == "echo":
        return EchoProvider()

    if choice in {"auto", "gemini"}:
        if not settings.gemini_api_key:
            if choice == "gemini":
                raise AgentError("provider='gemini' requires TILT_GEMINI_API_KEY.")
            return EchoProvider()
        from tilt.agents.gemini import GeminiProvider

        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            fallback_model=settings.gemini_fallback_model,
        )

    raise AgentError(f"Unknown provider: {settings.provider!r}")


__all__ = [
    "AgentError",
    "AgentProvider",
    "BudgetExceeded",
    "Completion",
    "EchoProvider",
    "MeteredProvider",
    "Pricing",
    "build_provider",
]
