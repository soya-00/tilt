"""Runtime settings the user can change from inside the app.

Distinct from :mod:`tilt.config`, which is boot configuration from the
environment. These can be edited while the service runs, so changing the API
key rebuilds the provider without a restart.

``settings.json`` lives **in the journal folder**, and it did not always. It was
moved out when the API key was sitting in it in plain text, which was the right
call about the key and the wrong one about everything else: the feeds you typed
and the model you chose are things you authored, and a folder advertised as your
whole journal that silently omitted them was not one. Copying it to another
machine lost both.

So the split is by secrecy rather than by convenience:

* **The journal folder** — model, ceiling, feeds. Yours, portable, and safe to
  grep, sync or commit.
* **The keychain** — the key, wherever the OS offers one.
* **A separate ``key.json`` in the support directory** — the key on a machine
  with no keychain, at mode 600. A separate file rather than dragging the whole
  settings file back out, so the rule keeps no exceptions: *nothing secret is
  ever written into the journal folder.*

``/status`` reports which of the last two is in force, because a silent
downgrade from "encrypted by the OS" to "plain text on disk" is worth saying out
loud.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

from tilt.secrets import Vault


def _read(path: Path) -> dict:
    """Whatever JSON is there, or nothing. A settings file somebody has hand
    edited into invalid JSON should cost them their settings, not their app."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


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
        self,
        path: Path,
        *,
        key_path: Path | None = None,
        ephemeral: bool = False,
        vault: Vault | None = None,
    ) -> None:
        self.path = path
        # Where the key goes when there is no keychain. Defaults beside the
        # settings file only so a caller that does not care still works; every
        # real caller passes a path outside the journal folder.
        self.key_path = key_path or path.with_name("key.json")
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
        settings = RuntimeSettings(**_read(self.path))
        # Never trusted from this file even if something put it there — an old
        # build, a hand edit, a restored backup. The key has exactly two homes
        # and this is not one of them.
        settings.gemini_api_key = ""

        if self.vault and self.vault.available:
            settings.gemini_api_key = self.vault.get() or ""
        else:
            settings.gemini_api_key = str(_read(self.key_path).get("gemini_api_key") or "")
        return settings

    def save(self, settings: RuntimeSettings) -> RuntimeSettings:
        if self.ephemeral:
            self._held = settings
            return settings

        key = settings.gemini_api_key.strip()
        if self.vault and not key:
            # An empty key here is an explicit "forget it", because every other
            # path carries the existing one through: `load` fills it from the
            # keychain and `update` only overwrites what the payload names.
            # Without this the file is cleared and the keychain is not, so the
            # key comes back on the next read and forgetting it does nothing.
            self.vault.clear()
        if not (self.vault and key and self.vault.set(key)):
            self._write_key(key)
        elif self.key_path.exists():
            # Promoted to the keychain, so the plaintext copy is stale and must
            # go rather than sit there readable.
            with contextlib.suppress(OSError):
                self.key_path.unlink()

        # The key is stripped unconditionally: this file is in the journal
        # folder, which someone is invited to sync and commit.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            settings.model_copy(update={"gemini_api_key": ""}).model_dump_json(indent=2),
            encoding="utf-8",
        )
        return settings

    def _write_key(self, key: str) -> None:
        """The fallback home, at mode 600, outside the journal."""
        if not key:
            with contextlib.suppress(OSError):
                self.key_path.unlink()
            return
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_text(json.dumps({"gemini_api_key": key}), encoding="utf-8")
        with contextlib.suppress(OSError):
            self.key_path.chmod(0o600)

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


def migrate(legacy: Path, path: Path, key_path: Path, *, vault: Vault | None = None) -> bool:
    """Move a pre-existing settings file into the journal folder.

    Somebody who has been using Tilt has feeds and a model chosen, and losing
    them on upgrade would be the same class of bug as the one this move fixes —
    only faster, and to the people who actually use it.

    The key is not carried across into the new file even if it is sitting in
    the old one. It goes to the keychain if there is one and to its own file if
    not, and the legacy file is removed either way so no plaintext copy is left
    behind in a directory nobody looks at again.
    """
    if path.exists() or not legacy.exists():
        return False

    data = _read(legacy)
    key = str(data.pop("gemini_api_key", "") or "").strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    if key and not (vault and vault.available and vault.set(key)):
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(json.dumps({"gemini_api_key": key}), encoding="utf-8")
        with contextlib.suppress(OSError):
            key_path.chmod(0o600)

    with contextlib.suppress(OSError):
        legacy.unlink()
    return True
