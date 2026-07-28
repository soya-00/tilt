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


class RuntimeSettings(BaseModel):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    monthly_cost_ceiling_usd: float = Field(default=20.0, ge=0)

    @property
    def has_key(self) -> bool:
        return bool(self.gemini_api_key.strip())


class RuntimeSettingsUpdate(BaseModel):
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    monthly_cost_ceiling_usd: float | None = Field(default=None, ge=0)


class PublicSettings(BaseModel):
    """What the UI is allowed to see. The key itself never leaves the machine."""

    has_key: bool
    key_hint: str
    gemini_model: str
    monthly_cost_ceiling_usd: float


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RuntimeSettings:
        try:
            return RuntimeSettings(**json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError):
            return RuntimeSettings()

    def save(self, settings: RuntimeSettings) -> RuntimeSettings:
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
        )
