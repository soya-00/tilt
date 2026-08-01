"""Health, configuration surface, and index maintenance."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from tilt import __version__
from tilt.agents.ledger import MeteredProvider
from tilt.api.deps import (
    get_journal,
    get_provider,
    get_settings_dep,
    get_settings_store,
)
from tilt.config import Settings
from tilt.embed import DORMANT_WITHOUT_KEY
from tilt.journal import Journal
from tilt.settings_store import SettingsStore

router = APIRouter(tags=["system"])


class Dormant(BaseModel):
    capability: str
    why: str


class Status(BaseModel):
    ok: bool
    version: str
    """Which build is actually answering.

    Reported by the service rather than the interface, because those are two
    separate processes that can be different versions — a rebuilt app bundle
    still carrying a stale frozen service is the exact confusion this settles."""
    provider: str
    offline: bool
    model: str
    entries: int
    spend_this_month_usd: float
    cost_ceiling_usd: float
    data_dir: str
    key_storage: str = "file"
    """Where the API key is kept: ``keychain``, ``file``, or ``memory``.

    Reported so the interface can say something true about it. A fallback from
    the OS keychain to a plain file is a real downgrade in how a credential is
    protected, and the app should name it rather than let someone assume the
    stronger one."""
    ephemeral: bool = False
    """Whether the key is held in memory rather than written to disk.

    Surfaced so Settings can say where the key goes and be right about it. The
    copy differs completely between the two, and a sentence promising a file
    mode to someone whose key is never filed would be worse than none."""
    dormant: list[Dormant] = []
    """What is asleep for want of a key, and why.

    Empty when a key is present. Said out loud rather than left to be noticed:
    without one the app still writes, files, connects and draws, so nothing
    looks broken — and the capabilities that are missing are exactly the ones
    you would never think to look for."""


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/status", response_model=Status)
def status(
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings_dep),
    store: SettingsStore = Depends(get_settings_store),
) -> Status:
    offline = provider.name == "echo"
    return Status(
        ok=True,
        version=__version__,
        provider=provider.name,
        offline=offline,
        model="offline" if offline else settings.gemini_model,
        entries=journal.index.count(authored_only=True),
        spend_this_month_usd=round(provider.spend_this_month(), 4),
        cost_ceiling_usd=settings.monthly_cost_ceiling_usd,
        data_dir=str(settings.data_dir),
        # Named from the store rather than guessed from configuration: the
        # keychain can be present and still refuse, and the honest answer is
        # what actually happened.
        key_storage=(
            "memory"
            if settings.ephemeral_settings
            else "keychain"
            if store.key_is_in_the_keychain
            else "file"
        ),
        ephemeral=settings.ephemeral_settings,
        dormant=(
            [Dormant(capability=name, why=why) for name, why in DORMANT_WITHOUT_KEY]
            if offline
            else []
        ),
    )


@router.post("/index/rebuild")
def rebuild_index(journal: Journal = Depends(get_journal)) -> dict[str, int]:
    """Discard the projection and rebuild it from Markdown on disk."""
    return {"indexed": journal.rebuild()}
