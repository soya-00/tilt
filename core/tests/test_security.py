"""What happens when someone tries to break it.

The interesting attacks against a journal that speaks HTTP are not injection —
every query is parameterised and the YAML loader is safe. They are economic and
about reach: spend somebody's money, fill their disk, read their journal from
the next desk, or make the service fetch something it should not.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tilt.agents.redact import redact
from tilt.api.app import create_app
from tilt.api.limits import MAX_REQUEST_BYTES, is_loopback
from tilt.config import Settings
from tilt.models import MAX_BODY
from tilt.settings_store import RuntimeSettingsUpdate, SettingsStore
from tilt.store.artifacts import ArtifactStore
from tilt.store.brief import BriefStore
from tilt.store.files import contained

# ------------------------------------------------------------------ exposure


def test_serving_off_loopback_without_a_token_is_refused(tmp_path: Path) -> None:
    """The one mistake with no recovery once someone has read your journal.

    Raised at startup rather than warned about: a warning in a log nobody reads
    is indistinguishable from no warning at all.
    """
    with pytest.raises(RuntimeError, match="TILT_AUTH_TOKEN"):
        create_app(Settings(data_dir=tmp_path, host="0.0.0.0", auth_token=None))


def test_loopback_without_a_token_still_works(tmp_path: Path) -> None:
    """What `npm run dev` does. Breaking it to be safe would be safety theatre
    paid for by everyone developing the app."""
    assert create_app(Settings(data_dir=tmp_path, host="127.0.0.1", auth_token=None))


def test_serving_off_loopback_with_a_token_is_allowed(tmp_path: Path) -> None:
    assert create_app(Settings(data_dir=tmp_path, host="0.0.0.0", auth_token="secret"))


def test_what_counts_as_this_machine_only() -> None:
    assert is_loopback("127.0.0.1")
    assert is_loopback("::1")
    assert is_loopback("localhost")
    assert not is_loopback("0.0.0.0")
    assert not is_loopback("192.168.1.10")
    # A hostname that is not an address literal is not provably loopback, and
    # guessing wrong in that direction leaves a journal open.
    assert not is_loopback("tilt.local")


# --------------------------------------------------------------------- size


def test_an_absurd_request_is_refused_before_it_is_read(client: TestClient) -> None:
    """Starlette buffers the body before a route ever sees it, so the check has
    to happen in middleware or not at all."""
    response = client.post(
        "/entries",
        json={"body": "x"},
        headers={"content-length": str(MAX_REQUEST_BYTES + 1)},
    )
    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]


def test_an_ordinary_entry_still_posts(client: TestClient) -> None:
    assert client.post("/entries", json={"body": "A thought."}).status_code == 201


def test_an_entry_longer_than_anyone_types_is_refused(client: TestClient) -> None:
    """The middleware only sees a declared content-length, which a chunked
    request does not send. This is the floor underneath it."""
    response = client.post("/entries", json={"body": "x" * (MAX_BODY + 1)})
    assert response.status_code == 422


# ---------------------------------------------------------------- traversal


def test_a_store_will_not_write_outside_its_own_directory(tmp_path: Path) -> None:
    """Not currently reachable through the router — uvicorn decodes the path
    before Starlette matches it — but a store should be safe on its own terms
    rather than because of how a web server happens to parse a URL."""
    root = tmp_path / "brief"
    for crafted in ("../../etc/passwd", "/etc/passwd", "a/../../b", "../sibling"):
        with pytest.raises(ValueError, match="does not name a file"):
            contained(root, crafted)

    # A bare ".." is not traversal: it names a file called "...md" *inside* the
    # directory. Asserted rather than left to inference, because the obvious
    # test to write here is the wrong one.
    assert contained(root, "..").parent == root


def test_a_crafted_id_reads_as_absent_rather_than_as_an_error(tmp_path: Path) -> None:
    """From the caller's side "no such item" and "not an id" want the same 404."""
    assert BriefStore(tmp_path).load("../../etc/passwd") is None
    assert BriefStore(tmp_path).remove("../../etc/passwd") is False
    assert ArtifactStore(tmp_path).load("../../etc/passwd") is None
    assert ArtifactStore(tmp_path).delete("../../etc/passwd") is False


def test_a_file_renamed_by_hand_is_still_reachable(tmp_path: Path) -> None:
    """These directories are Markdown the user is invited to edit. Checking the
    *shape* of the id was the first attempt and broke that promise; containment
    is what actually matters."""
    assert contained(tmp_path, "my-diagram").name == "my-diagram.md"


# ----------------------------------------------------- serving the page too


def interface(tmp_path: Path) -> Settings:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html><body>Tilt</body></html>")
    (static / "assets" / "app.js").write_text("// built")
    return Settings(
        data_dir=tmp_path / "journal",
        static_dir=static,
        auth_token="secret",
        schedule_enabled=False,
    )


def test_the_page_is_reachable_without_the_token(tmp_path: Path) -> None:
    """Open by necessity, not by choice: a browser cannot attach an
    Authorization header to a document request, and the page is what carries
    the token to the API. Recorded so nobody later reads this as the token
    being the perimeter — it is not, in this topology."""
    with TestClient(create_app(interface(tmp_path))) as client:
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200


def test_the_journal_behind_it_is_not(tmp_path: Path) -> None:
    """The point of the token surviving at all: reaching the port directly,
    without ever loading the page, gets you nothing."""
    with TestClient(create_app(interface(tmp_path))) as client:
        assert client.get("/entries").status_code == 401
        assert client.get("/settings").status_code == 401
        assert client.post("/entries", json={"body": "x"}).status_code == 401

        ok = client.get("/entries", headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 200


def test_serving_the_page_does_not_loosen_the_desktop_app(tmp_path: Path) -> None:
    """Without static_dir this process is an API and nothing else, so the gate
    stays total — a stray file named index.html cannot open a door."""
    settings = Settings(data_dir=tmp_path, auth_token="secret", schedule_enabled=False)
    with TestClient(create_app(settings)) as client:
        assert client.get("/index.html").status_code == 401


# ---------------------------------------------------------- somebody's key


def test_ephemeral_settings_never_touch_the_disk(tmp_path: Path) -> None:
    """For a demo where the person typing the key does not own the machine.

    The point is being able to say "it is never written down" and have that be
    true, rather than asking a stranger to trust a file mode.
    """
    path = tmp_path / "settings.json"
    store = SettingsStore(path, ephemeral=True)

    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaSECRET"))

    assert not path.exists()
    assert store.load().gemini_api_key == "AIzaSECRET", "still usable this session"
    assert store.public().key_hint == "…CRET"


def test_a_new_process_starts_without_the_key(tmp_path: Path) -> None:
    """Held in the store, not in a module global. A second instance over the
    same path — which is what a restart is — begins empty."""
    path = tmp_path / "settings.json"
    SettingsStore(path, ephemeral=True).update(
        RuntimeSettingsUpdate(gemini_api_key="AIzaSECRET")
    )

    assert SettingsStore(path, ephemeral=True).load().gemini_api_key == ""


def test_the_ordinary_store_still_persists(tmp_path: Path) -> None:
    """The default, and the right one on your own machine: a key that survives
    a restart is the point."""
    path = tmp_path / "settings.json"
    SettingsStore(path).update(RuntimeSettingsUpdate(gemini_api_key="AIzaKEEP"))

    assert path.exists()
    assert SettingsStore(path).load().gemini_api_key == "AIzaKEEP"


# ---------------------------------------------------------------- redaction


def test_a_key_never_reaches_the_client_through_an_error() -> None:
    """Provider errors are relayed as 502 bodies, which is right — "your key is
    not valid" is worth reading. It is also the one place a credential could
    surface, and under bring-your-own-key it is somebody else's."""
    leaky = (
        "400 INVALID_ARGUMENT: request to "
        "https://generativelanguage.googleapis.com/v1/models?key=AIzaSyC7fake_KEY_material99 "
        "failed; Authorization: Bearer ya29.a0AfB_longlivedtokenvalue"
    )

    clean = redact(leaky)

    assert "AIzaSyC7fake_KEY_material99" not in clean
    assert "ya29.a0AfB_longlivedtokenvalue" not in clean
    assert "key=AIza" not in clean
    # The diagnostic survives — that is the whole reason errors are relayed.
    assert "INVALID_ARGUMENT" in clean


def test_redaction_leaves_an_ordinary_message_alone() -> None:
    message = "Gemini returned an empty response."
    assert redact(message) == message
