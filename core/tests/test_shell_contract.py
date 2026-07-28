"""The contract between the core service and the desktop shell.

Two things pass across that boundary and both are easy to break silently: the
ready line the shell parses to learn the port, and the bearer token that keeps
every other process on the machine out of the journal.
"""

from __future__ import annotations

import io
import json
import os
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tilt import serve
from tilt.api.app import create_app
from tilt.config import Settings, get_settings
from tilt.serve import READY_PREFIX, _bind, announce

TOKEN = "test-token-value"


@pytest.fixture
def guarded(settings: Settings) -> TestClient:
    settings.auth_token = TOKEN
    with TestClient(create_app(settings)) as c:
        yield c


def test_health_needs_no_token(guarded: TestClient) -> None:
    """How the shell learns the sidecar is up, before it knows anything else."""
    assert guarded.get("/health").status_code == 200


def test_journal_is_closed_without_a_token(guarded: TestClient) -> None:
    response = guarded.get("/entries")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authorised."


def test_wrong_token_is_rejected(guarded: TestClient) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}x"}
    assert guarded.get("/entries", headers=headers).status_code == 401


def test_a_non_bearer_scheme_is_not_enough(guarded: TestClient) -> None:
    assert guarded.get("/entries", headers={"Authorization": TOKEN}).status_code == 401


def test_the_token_opens_everything(guarded: TestClient) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert guarded.get("/entries", headers=headers).status_code == 200
    assert guarded.post("/entries", json={"body": "a thought"}, headers=headers).status_code == 201


def test_preflight_passes_unauthenticated(guarded: TestClient) -> None:
    """Browsers send OPTIONS with no Authorization header. Gate it and every
    cross-origin call fails before it is ever made."""
    response = guarded.options(
        "/entries",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_a_rejection_still_carries_cors_headers(guarded: TestClient) -> None:
    """Otherwise the webview sees an unreadable network error instead of 401."""
    response = guarded.get("/entries", headers={"Origin": "tauri://localhost"})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_no_token_configured_leaves_the_service_open(client: TestClient) -> None:
    """Running uvicorn by hand for development must keep working."""
    assert client.get("/entries").status_code == 200


def test_ready_line_is_one_parseable_line() -> None:
    stream = io.StringIO()
    announce("127.0.0.1", 51234, stream=stream)
    written = stream.getvalue()

    assert written.count("\n") == 1
    assert written.startswith(READY_PREFIX)
    assert json.loads(written[len(READY_PREFIX) :]) == {"host": "127.0.0.1", "port": 51234}


class _FakeServer:
    should_exit = False


def test_the_core_stops_when_its_parent_goes_away() -> None:
    """The shell kills the core on quit, but a crash on its side skips that.
    Losing the pipe is the backstop that keeps an invisible server from holding
    someone's journal open."""
    read_fd, write_fd = os.pipe()
    server = _FakeServer()

    with os.fdopen(read_fd) as pipe:
        thread = serve.watch_parent(server, stream=pipe)  # type: ignore[arg-type]
        assert server.should_exit is False

        os.close(write_fd)  # the parent dies
        thread.join(timeout=5)

    assert thread.is_alive() is False
    assert server.should_exit is True


def test_self_check_touches_no_real_journal(tmp_path: Path, monkeypatch) -> None:
    """It runs on whichever machine packaged the build, and it must not leave a
    Tilt folder in the home directory of a release engineer."""
    monkeypatch.setenv("HOME", str(tmp_path))
    get_settings.cache_clear()

    assert serve.self_check() == 0
    assert not (tmp_path / "Tilt").exists()

    get_settings.cache_clear()


def test_port_zero_resolves_to_a_real_port() -> None:
    """The shell asks for any free port so two copies never collide."""
    sock = _bind("127.0.0.1", 0)
    try:
        assert sock.getsockname()[1] > 0
        assert sock.family is socket.AF_INET
    finally:
        sock.close()
