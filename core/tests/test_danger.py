"""The two things in the app that take something away.

Forgetting the key and erasing everything are the only routes that destroy
rather than derive, and they fail in opposite directions. A forget that leaves
the key behind is a security claim that is not true; an erase that fires without
being asked is somebody's journal.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tilt.config import Settings
from tilt.secrets import Vault
from tilt.settings_store import RuntimeSettings, RuntimeSettingsUpdate, SettingsStore


class FakeVault(Vault):
    """A keychain that works, so the fallback path is not what is being tested."""

    def __init__(self) -> None:
        self.stored: str | None = None

    @property
    def available(self) -> bool:
        return True

    def get(self) -> str | None:
        return self.stored

    def set(self, value: str) -> bool:
        self.stored = value
        return True

    def clear(self) -> None:
        self.stored = None


# ------------------------------------------------------------ forgetting a key


def test_an_empty_key_clears_the_keychain(tmp_path: Path) -> None:
    """The bug this exists for: clearing the file and not the keychain looks
    like it worked, and the key is back on the next read."""
    vault = FakeVault()
    store = SettingsStore(tmp_path / "settings.json", vault=vault)
    store.save(RuntimeSettings(gemini_api_key="AIzaSecret"))
    assert vault.stored == "AIzaSecret"

    store.update(RuntimeSettingsUpdate(gemini_api_key=""))

    assert vault.stored is None
    assert store.load().gemini_api_key == ""
    assert store.public().has_key is False


def test_forgetting_it_does_not_take_the_feeds_with_it(tmp_path: Path) -> None:
    """The other half of the panel is right beside this one."""
    store = SettingsStore(tmp_path / "settings.json", vault=FakeVault())
    store.update(
        RuntimeSettingsUpdate(gemini_api_key="AIzaSecret", feeds=["https://example.com/f.xml"])
    )

    store.update(RuntimeSettingsUpdate(gemini_api_key=""))

    assert store.load().feeds == ["https://example.com/f.xml"]


def test_a_normal_save_does_not_forget_the_key(tmp_path: Path) -> None:
    """Every other path carries the existing key through, and must keep doing
    so — otherwise editing a feed URL would silently sign you out."""
    vault = FakeVault()
    store = SettingsStore(tmp_path / "settings.json", vault=vault)
    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaSecret"))

    store.update(RuntimeSettingsUpdate(feeds=["https://example.com/f.xml"]))

    assert vault.stored == "AIzaSecret"


def test_the_key_is_never_left_in_the_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path, vault=FakeVault())
    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaSecret"))

    assert "AIzaSecret" not in path.read_text()


# ------------------------------------------------------------------- erasing


def test_erasing_needs_the_word(client: TestClient, settings: Settings) -> None:
    """The only route that destroys writing, so it must be unreachable by a
    mis-fired request, a replay, or a handler that fires twice."""
    assert client.post("/erase", json={}).status_code == 400
    assert client.post("/erase", json={"confirm": "delete"}).status_code == 400
    assert client.post("/erase", json={"confirm": "yes"}).status_code == 400

    assert settings.data_dir.exists(), "nothing should have been touched"


def test_erasing_removes_both_directories(client: TestClient, settings: Settings) -> None:
    client.post("/entries", json={"body": "Something I wrote."})
    assert list(settings.entries_dir.rglob("*.md"))

    body = client.post("/erase", json={"confirm": "DELETE"}).json()

    assert not settings.data_dir.exists()
    assert not settings.internal_dir.exists()
    assert str(settings.data_dir) in body["removed"]
    assert str(settings.internal_dir) in body["removed"]


def test_it_says_what_it_removed(client: TestClient, settings: Settings) -> None:
    """Named by full path. Somebody about to lose a journal should be able to
    check afterwards that it was the one they meant."""
    removed = client.post("/erase", json={"confirm": "DELETE"}).json()["removed"]

    assert all(Path(p).is_absolute() for p in removed)


def test_nothing_stops_the_server_when_there_is_no_server(client: TestClient) -> None:
    """Under a test client there is no uvicorn to take down, so the route is
    inert on that half by construction rather than by anyone stubbing it — the
    reason this test suite can call it at all."""
    assert not hasattr(client.app.state, "server")

    assert client.post("/erase", json={"confirm": "DELETE"}).status_code == 200
