"""Where the API key actually lives.

The key used to sit in ``settings.json`` in plain text. That was defensible
while it was the only option and indefensible once it was not: any process
running as you can read that file, and on macOS there is a system service whose
entire job is to hold exactly this.

So the key goes to the OS keychain, and ``settings.json`` keeps only the things
that are not secret — the model, the ceiling, the feed list.

**What this does not change**, said plainly because the README used to promise
otherwise: the key still arrives over loopback HTTP through ``PATCH /settings``.
Moving that too would mean a second owner of the key in the Tauri shell, a way
to tell the sidecar it changed, and a reload path — a great deal of machinery to
close a hole that is a request you made yourself, from the app's own webview,
behind a bearer token. The plaintext file was the real exposure. This closes it.

Three states, in precedence order, because each answers a different question:

1. **Ephemeral** — a shared demo where the person typing the key does not own
   the machine. Nothing is stored anywhere and the keychain is never touched.
2. **A keychain exists** — the ordinary desktop case.
3. **None does** — a container, CI, a headless Linux box with no Secret
   Service. Falls back to the file, and *says so*, because a silent downgrade
   from "encrypted by the OS" to "plain text on disk" is the kind of thing
   someone should be told about rather than left to discover.
"""

from __future__ import annotations

import contextlib
import logging

log = logging.getLogger(__name__)

SERVICE = "id.tilt.app"
"""Matches the bundle identifier in ``tauri.conf.json``, so the keychain entry
is recognisable as this app's when someone goes looking in Keychain Access."""

ACCOUNT = "gemini-api-key"


class Vault:
    """The OS keychain, or an honest report that there is not one.

    Constructed once and asked ``available`` thereafter. Probing on every call
    would mean a keychain prompt per request on macOS, and the answer does not
    change while the process runs.
    """

    def __init__(self, *, service: str = SERVICE, account: str = ACCOUNT) -> None:
        self.service = service
        self.account = account
        self._keyring = self._probe()

    @staticmethod
    def _probe():
        """The backend, or ``None`` if there is nothing usable here.

        ``keyring`` always returns *a* backend; on a box with no keychain it is
        ``fail.Keyring``, which raises on use. Asking its priority is how you
        find out before you rely on it, rather than at the first write.
        """
        try:
            import keyring
            from keyring.backends import fail
        except ImportError:  # pragma: no cover - keyring is a declared dependency
            log.warning("keyring is not installed; the API key will be stored in a file")
            return None

        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring):
            log.info("no OS keychain here; the API key will be stored in a file")
            return None
        return keyring

    @property
    def available(self) -> bool:
        return self._keyring is not None

    def get(self) -> str | None:
        if self._keyring is None:
            return None
        try:
            return self._keyring.get_password(self.service, self.account)
        except Exception:  # noqa: BLE001 - a locked or refused keychain
            # Not fatal. The caller falls back to the file, and the app works
            # without a key at all — losing the ability to reflect because a
            # keychain prompt was dismissed would be absurd.
            log.warning("could not read the key from the keychain", exc_info=True)
            return None

    def set(self, value: str) -> bool:
        """Store it. ``False`` means the caller should fall back to the file."""
        if self._keyring is None:
            return False
        try:
            self._keyring.set_password(self.service, self.account, value)
            return True
        except Exception:  # noqa: BLE001
            log.warning("could not write the key to the keychain", exc_info=True)
            return False

    def clear(self) -> None:
        if self._keyring is None:
            return
        # Already absent is the common case, and is not a failure.
        with contextlib.suppress(Exception):
            self._keyring.delete_password(self.service, self.account)
