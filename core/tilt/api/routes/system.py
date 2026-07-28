"""Health, configuration surface, and index maintenance."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from tilt.agents.ledger import MeteredProvider
from tilt.api.deps import get_journal, get_provider, get_settings_dep
from tilt.config import Settings
from tilt.journal import Journal

router = APIRouter(tags=["system"])


class Status(BaseModel):
    ok: bool
    provider: str
    offline: bool
    model: str
    entries: int
    spend_this_month_usd: float
    cost_ceiling_usd: float
    data_dir: str


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/status", response_model=Status)
def status(
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings_dep),
) -> Status:
    offline = provider.name == "echo"
    return Status(
        ok=True,
        provider=provider.name,
        offline=offline,
        model="offline" if offline else settings.gemini_model,
        entries=journal.index.count(authored_only=True),
        spend_this_month_usd=round(provider.spend_this_month(), 4),
        cost_ceiling_usd=settings.monthly_cost_ceiling_usd,
        data_dir=str(settings.data_dir),
    )


@router.post("/index/rebuild")
def rebuild_index(journal: Journal = Depends(get_journal)) -> dict[str, int]:
    """Discard the projection and rebuild it from Markdown on disk."""
    return {"indexed": journal.rebuild()}
