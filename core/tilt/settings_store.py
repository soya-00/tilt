"""Runtime settings the user can change from inside the app.

Distinct from :mod:`tilt.config`, which is boot configuration from the
environment. These live in ``.tilt/settings.json`` beside the journal and can be
edited while the service runs — changing the API key rebuilds the provider
without a restart.

The key is stored in plain text on disk. That is acceptable for a local-only
app you run yourself, and it is what lets the key travel with your journal
folder. The Tauri build should move it to the macOS Keychain.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

MAX_FEEDS = 20
"""More than anyone reads, and few enough that one pass cannot take all
morning. Each feed is a request the scout makes before it decides anything."""


def clean_feeds(urls: list[str]) -> list[str]:
    """Trim, drop blanks and duplicates, and refuse anything that is not http.

    A ``file://`` or ``data:`` URL here would make the scout fetch from the
    machine it runs on, which is not what "watch a publication" means to anyone
    typing into that box.
    """
    out: list[str] = []
    for raw in urls:
        url = raw.strip()
        if url.startswith(("http://", "https://")) and url not in out:
            out.append(url)
    return out[:MAX_FEEDS]


class RuntimeSettings(BaseModel):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    monthly_cost_ceiling_usd: float = Field(default=20.0, ge=0)
    feeds: list[str] = Field(default_factory=list)
    """Atom or RSS URLs the scout should watch, edited from inside the app.

    Runtime rather than boot configuration, because which publications are
    worth following is a thing you change your mind about — and changing it
    should not mean restarting the service."""

    @property
    def has_key(self) -> bool:
        return bool(self.gemini_api_key.strip())


class RuntimeSettingsUpdate(BaseModel):
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    monthly_cost_ceiling_usd: float | None = Field(default=None, ge=0)
    feeds: list[str] | None = None


class PublicSettings(BaseModel):
    """What the UI is allowed to see. The key itself never leaves the machine."""

    has_key: bool
    key_hint: str
    gemini_model: str
    monthly_cost_ceiling_usd: float
    feeds: list[str] = Field(default_factory=list)
    """Not a secret, unlike the key — these are addresses of public pages, and
    the whole point of them being here is that you can see and change which
    ones the scout watches."""


class SettingsStore:
    """Runtime settings, on disk or only in memory.

    ``ephemeral`` exists for a shared demo, where the person typing the key is
    not the person who owns the machine. Nothing is written, so the key lives
    for the life of the process and the app can say so truthfully rather than
    asking a stranger to trust a file mode.
    """

    def __init__(self, path: Path, *, ephemeral: bool = False) -> None:
        self.path = path
        self.ephemeral = ephemeral
        self._held: RuntimeSettings | None = None

    def load(self) -> RuntimeSettings:
        if self.ephemeral:
            return (self._held or RuntimeSettings()).model_copy(deep=True)
        try:
            return RuntimeSettings(**json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError):
            return RuntimeSettings()

    def save(self, settings: RuntimeSettings) -> RuntimeSettings:
        if self.ephemeral:
            self._held = settings
            return settings
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        # Owner-only: the file holds an API key. Best effort — some
        # filesystems (and Windows) do not support the mode.
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)
        return settings

    def update(self, payload: RuntimeSettingsUpdate) -> RuntimeSettings:
        current = self.load()
        if payload.gemini_api_key is not None:
            current.gemini_api_key = payload.gemini_api_key.strip()
        if payload.gemini_model is not None:
            current.gemini_model = payload.gemini_model.strip() or current.gemini_model
        if payload.monthly_cost_ceiling_usd is not None:
            current.monthly_cost_ceiling_usd = payload.monthly_cost_ceiling_usd
        if payload.feeds is not None:
            current.feeds = clean_feeds(payload.feeds)
        return self.save(current)

    def public(self) -> PublicSettings:
        s = self.load()
        key = s.gemini_api_key.strip()
        return PublicSettings(
            has_key=bool(key),
            # Enough to recognise which key is set, never enough to use it.
            key_hint=f"…{key[-4:]}" if len(key) >= 4 else "",
            gemini_model=s.gemini_model,
            monthly_cost_ceiling_usd=s.monthly_cost_ceiling_usd,
            feeds=s.feeds,
        )
