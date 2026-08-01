"""Runtime settings the user can change from inside the app.

Distinct from :mod:`tilt.config`, which is boot configuration from the
environment. These live in ``settings.json`` in the support directory — outside
the journal — and can be edited while the service runs, so changing the API key
rebuilds the provider without a restart.

Outside the journal deliberately. The journal folder is one you are invited to
grep, sync and put in git, and a live credential has no business in it.

The key is not in this file at all where the OS offers somewhere better: it
goes to the keychain via :mod:`tilt.secrets`, and what stays here is the model,
the ceiling and the feed list — none of which are secret. Where there is no
keychain the key falls back to this file at mode 600, and ``/status`` reports
which of the two is in force, because a silent downgrade from "encrypted by the
OS" to "plain text on disk" is worth saying out loud.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

from tilt.secrets import Vault

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

    def __init__(
        self, path: Path, *, ephemeral: bool = False, vault: Vault | None = None
    ) -> None:
        self.path = path
        self.ephemeral = ephemeral
        # Not constructed when ephemeral: there is nothing to store, and
        # probing a keychain would prompt on macOS for no reason.
        self.vault = None if ephemeral else (vault or Vault())
        self._held: RuntimeSettings | None = None

    @property
    def key_is_in_the_keychain(self) -> bool:
        """Whether the key is protected by the OS rather than by a file mode.

        Reported through ``/status`` so a fallback to plain text is visible.
        Silently downgrading how a credential is stored is exactly the kind of
        thing someone should be told about."""
        return bool(self.vault and self.vault.available)

    def load(self) -> RuntimeSettings:
        if self.ephemeral:
            return (self._held or RuntimeSettings()).model_copy(deep=True)
        try:
            settings = RuntimeSettings(
                **json.loads(self.path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, ValueError):
            settings = RuntimeSettings()

        # The keychain wins over the file. A key in both means an upgrade
        # happened and the file's copy is the stale one.
        if self.vault and self.vault.available:
            settings.gemini_api_key = self.vault.get() or ""
        return settings

    def save(self, settings: RuntimeSettings) -> RuntimeSettings:
        if self.ephemeral:
            self._held = settings
            return settings

        stored = settings
        key = settings.gemini_api_key.strip()
        if self.vault and not key:
            # An empty key here is an explicit "forget it", because every other
            # path carries the existing one through: `load` fills it from the
            # keychain and `update` only overwrites what the payload names.
            # Without this the file is cleared and the keychain is not, so the
            # key comes back on the next read and forgetting it does nothing.
            self.vault.clear()
        if self.vault and key and self.vault.set(key):
            # Written to the file with the key removed, so an existing
            # plaintext copy is overwritten rather than left behind.
            stored = settings.model_copy(update={"gemini_api_key": ""})

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(stored.model_dump_json(indent=2), encoding="utf-8")
        # Owner-only. Still worth doing when the key is in the keychain: the
        # ceiling and the feed list are nobody else's business either, and this
        # is the fallback path's only protection.
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
