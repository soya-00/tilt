"""Whether the journal folder is really the whole journal.

The app's rule is that the folder holds what you authored and the support
directory holds what the machine derived. Two things you authored were on the
wrong side of that line: the feeds you typed and the model you chose. Copying
`~/Tilt` to another machine lost both, silently, from a folder advertised as
your whole journal.

These tests are the claim: put the folder somewhere else, boot against it, and
find everything still there.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tilt.api.app import create_app
from tilt.config import Settings
from tilt.settings_store import SettingsStore, migrate


class FakeVault:
    """A keychain that works, so the fallback is not what is under test."""

    def __init__(self, *, works: bool = True) -> None:
        self.works = works
        self.stored: str | None = None

    @property
    def available(self) -> bool:
        return self.works

    def get(self) -> str | None:
        return self.stored if self.works else None

    def set(self, value: str) -> bool:
        if not self.works:
            return False
        self.stored = value
        return True

    def clear(self) -> None:
        self.stored = None


def moved(source: Settings, root: Path) -> Settings:
    """The same journal folder, opened on a machine that has never seen it.

    Copies only the journal — a fresh support directory is the whole point, and
    carrying the old one across would prove nothing.
    """
    import shutil

    destination = root / "moved"
    shutil.copytree(source.data_dir, destination)
    return Settings(
        data_dir=destination,
        support_dir=root / "elsewhere",
        provider="echo",
        schedule_enabled=False,
    )


# ------------------------------------------------------- what travels with it


def test_the_feeds_you_typed_travel(client: TestClient, settings: Settings, tmp_path) -> None:
    """The gap this closes. They lived in the support directory, so a journal
    handed to another machine arrived with the scout looking at nothing."""
    client.patch("/settings", json={"feeds": ["https://example.com/feed.xml"]})

    with TestClient(create_app(moved(settings, tmp_path))) as second:
        assert second.get("/settings").json()["feeds"] == ["https://example.com/feed.xml"]


def test_the_model_you_chose_travels(client: TestClient, settings: Settings, tmp_path) -> None:
    client.patch("/settings", json={"gemini_model": "gemini-3.5-flash"})

    with TestClient(create_app(moved(settings, tmp_path))) as second:
        assert second.get("/settings").json()["gemini_model"] == "gemini-3.5-flash"


def test_your_writing_and_your_decisions_travel(
    client: TestClient, settings: Settings, tmp_path
) -> None:
    """The parts that already worked, asserted here so the whole claim is in one
    place rather than spread across the suite it was proved in."""
    client.post("/entries", json={"body": "Attention behaves like a filter."})
    client.patch("/agent/persona", json={"name": "Compass"})

    with TestClient(create_app(moved(settings, tmp_path))) as second:
        assert second.get("/status").json()["entries"] == 1
        assert second.get("/agent/persona").json()["name"] == "Compass"


def test_the_key_does_not_travel(client: TestClient, settings: Settings, tmp_path) -> None:
    """The one thing that must not. A credential copied into a folder somebody
    syncs, commits or hands to a colleague is the whole reason settings were
    moved out of here in the first place."""
    client.patch("/settings", json={"gemini_api_key": "AIzaSecret"})

    for path in settings.data_dir.rglob("*"):
        if path.is_file():
            assert "AIzaSecret" not in path.read_text(errors="ignore"), path

    with TestClient(create_app(moved(settings, tmp_path))) as second:
        assert second.get("/settings").json()["has_key"] is False


# --------------------------------------------------- upgrading an existing one


def test_an_existing_settings_file_is_carried_over(tmp_path: Path) -> None:
    """Anyone already using Tilt has feeds and a model chosen. Losing them on
    upgrade would be this same bug, only faster and aimed at the people who
    actually use it."""
    legacy = tmp_path / "support" / "settings.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps(
            {
                "gemini_model": "gemini-3.5-flash",
                "feeds": ["https://example.com/feed.xml"],
                "monthly_cost_ceiling_usd": 5.0,
            }
        )
    )
    path = tmp_path / "journal" / "settings.json"

    assert migrate(legacy, path, tmp_path / "support" / "key.json") is True

    moved_in = SettingsStore(path, key_path=tmp_path / "support" / "key.json").load()
    assert moved_in.feeds == ["https://example.com/feed.xml"]
    assert moved_in.gemini_model == "gemini-3.5-flash"
    assert moved_in.monthly_cost_ceiling_usd == 5.0
    assert not legacy.exists(), "and the old copy does not linger"


def test_a_key_in_the_old_file_goes_to_the_keychain(tmp_path: Path) -> None:
    """Not into the new file. It is about to sit in a folder people sync."""
    legacy = tmp_path / "support" / "settings.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"gemini_api_key": "AIzaOld", "feeds": []}))
    path = tmp_path / "journal" / "settings.json"
    vault = FakeVault()

    migrate(legacy, path, tmp_path / "support" / "key.json", vault=vault)

    assert vault.stored == "AIzaOld"
    assert "AIzaOld" not in path.read_text()


def test_a_key_with_no_keychain_goes_to_its_own_file(tmp_path: Path) -> None:
    legacy = tmp_path / "support" / "settings.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"gemini_api_key": "AIzaOld"}))
    path = tmp_path / "journal" / "settings.json"
    key_path = tmp_path / "support" / "key.json"

    migrate(legacy, path, key_path, vault=FakeVault(works=False))

    assert json.loads(key_path.read_text())["gemini_api_key"] == "AIzaOld"
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert "AIzaOld" not in path.read_text()


def test_it_never_overwrites_settings_you_already_have(tmp_path: Path) -> None:
    """Runs on every boot, so it has to be a no-op on all but the first."""
    legacy = tmp_path / "support" / "settings.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"feeds": ["https://old.example/rss"]}))
    path = tmp_path / "journal" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"feeds": ["https://current.example/rss"]}))

    assert migrate(legacy, path, tmp_path / "support" / "key.json") is False
    assert "current.example" in path.read_text()


def test_nothing_to_migrate_is_not_an_error(tmp_path: Path) -> None:
    """Every new journal, and every boot after the first."""
    assert migrate(tmp_path / "nope.json", tmp_path / "new.json", tmp_path / "key.json") is False


# ----------------------------------------------------------- one file, and back


def test_an_archive_round_trips(client: TestClient, settings: Settings) -> None:
    """The test that makes this a claim rather than a hope: export, destroy,
    import, and find the journal where it was."""
    client.post("/entries", json={"body": "Attention behaves like a filter."})
    client.patch("/settings", json={"feeds": ["https://example.com/feed.xml"]})
    written = Path(client.post("/export").json()["path"])

    import shutil

    shutil.rmtree(settings.data_dir)

    body = client.post(
        "/import", json={"path": str(written), "confirm": "REPLACE"}
    ).json()

    assert body["entries"] == 1
    assert (settings.data_dir / "settings.json").exists()
    with TestClient(create_app(settings)) as after:
        assert after.get("/status").json()["entries"] == 1
        assert after.get("/settings").json()["feeds"] == ["https://example.com/feed.xml"]


def test_the_archive_is_written_outside_the_journal(
    client: TestClient, settings: Settings
) -> None:
    """Beside the journal was the obvious choice and the wrong one: journals
    live in synced folders, and an archive dropped next to one uploads a second
    complete copy of everything without saying so."""
    written = Path(client.post("/export").json()["path"])

    assert settings.internal_dir in written.parents
    assert settings.data_dir not in written.parents


def test_no_key_is_ever_in_an_archive(client: TestClient, settings: Settings) -> None:
    """The check that has to keep passing as the contents grow."""
    import zipfile

    client.patch("/settings", json={"gemini_api_key": "AIzaSecret"})
    written = Path(client.post("/export").json()["path"])

    with zipfile.ZipFile(written) as archive:
        for name in archive.namelist():
            assert b"AIzaSecret" not in archive.read(name), name


def test_importing_needs_the_word(client: TestClient, settings: Settings) -> None:
    written = client.post("/export").json()["path"]
    client.post("/entries", json={"body": "Written after the export."})

    assert client.post("/import", json={"path": written}).status_code == 400

    assert client.get("/status").json()["entries"] == 1, "and nothing was replaced"


def test_an_archive_from_a_newer_tilt_is_refused(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    """Refused rather than half-loaded. The index rebuilds from Markdown either
    way, so most of it would look like it worked — and the parts that silently
    did not would be whatever this version has never heard of."""
    import json
    import zipfile

    from tilt.store.index import SCHEMA_VERSION

    future = tmp_path / "future.zip"
    with zipfile.ZipFile(future, "w") as archive:
        archive.writestr("tilt.json", json.dumps({"schema": SCHEMA_VERSION + 1}))
        archive.writestr("journal/entries/a.md", "hello")

    response = client.post("/import", json={"path": str(future), "confirm": "REPLACE"})

    assert response.status_code == 400
    assert "newer Tilt" in response.json()["detail"]
    assert settings.data_dir.exists(), "and it stopped before touching anything"


def test_something_that_is_not_an_archive_is_refused(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    junk = tmp_path / "holiday.zip"
    junk.write_bytes(b"not a zip at all")

    response = client.post("/import", json={"path": str(junk), "confirm": "REPLACE"})

    assert response.status_code == 400
    assert settings.data_dir.exists()


def test_a_member_that_climbs_out_of_the_folder_is_dropped(tmp_path: Path) -> None:
    """An archive is an untrusted file that arrived from somewhere, and
    `../../.ssh/authorized_keys` is the oldest trick there is."""
    import json
    import zipfile

    from tilt import archive as arc
    from tilt.store.index import SCHEMA_VERSION

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("tilt.json", json.dumps({"schema": SCHEMA_VERSION}))
        archive.writestr("journal/entries/fine.md", "kept")
        archive.writestr("journal/../../escaped.md", "should never be written")

    data_dir = tmp_path / "journal"
    arc.restore(evil, data_dir=data_dir, vectors=None)

    assert (data_dir / "entries" / "fine.md").exists()
    assert not (tmp_path.parent / "escaped.md").exists()
    assert not (tmp_path / "escaped.md").exists()
