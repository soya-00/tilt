"""What happens when someone tries to break it.

The interesting attacks against a journal that speaks HTTP are not injection —
every query is parameterised and the YAML loader is safe. They are economic and
about reach: spend somebody's money, fill their disk, read their journal from
the next desk, or make the service fetch something it should not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tilt.agents.redact import redact
from tilt.api.app import create_app
from tilt.api.limits import MAX_REQUEST_BYTES, is_loopback
from tilt.config import Settings
from tilt.journal import Journal
from tilt.models import MAX_BODY
from tilt.serve import hold_journal
from tilt.settings_store import RuntimeSettingsUpdate, SettingsStore
from tilt.store.artifacts import ArtifactStore
from tilt.store.brief import BriefStore
from tilt.store.files import contained, path_for
from tilt.store.index import Index

# ------------------------------------------------------------------ exposure


def exposed(tmp_path: Path, *, host: str, auth_token: str | None) -> Settings:
    """Settings that keep the index out of the real user's support directory."""
    return Settings(
        data_dir=tmp_path,
        support_dir=tmp_path / "support",
        host=host,
        auth_token=auth_token,
        schedule_enabled=False,
    )


def test_serving_off_loopback_without_a_token_is_refused(tmp_path: Path) -> None:
    """The one mistake with no recovery once someone has read your journal.

    Raised at startup rather than warned about: a warning in a log nobody reads
    is indistinguishable from no warning at all.
    """
    with pytest.raises(RuntimeError, match="TILT_AUTH_TOKEN"):
        create_app(exposed(tmp_path, host="0.0.0.0", auth_token=None))


def test_loopback_without_a_token_still_works(tmp_path: Path) -> None:
    """What `npm run dev` does. Breaking it to be safe would be safety theatre
    paid for by everyone developing the app."""
    assert create_app(exposed(tmp_path, host="127.0.0.1", auth_token=None))


def test_serving_off_loopback_with_a_token_is_allowed(tmp_path: Path) -> None:
    assert create_app(exposed(tmp_path, host="0.0.0.0", auth_token="secret"))


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
        support_dir=tmp_path / "support",
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
    settings = Settings(
        data_dir=tmp_path,
        support_dir=tmp_path / "support",
        auth_token="secret",
        schedule_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/index.html").status_code == 401


# ------------------------------------------------- what goes in which folder


def test_nothing_the_machine_derived_lands_in_the_journal(tmp_path: Path) -> None:
    """The line the split exists to draw.

    The journal folder is one you are invited to grep, put in git, and hand to
    a cloud provider. An API key and a WAL-mode database are both hazardous
    under that invitation, and macOS syncs ~/Documents by default — so this is
    not hypothetical for anyone who keeps their journal in the obvious place.
    """
    settings = Settings(data_dir=tmp_path / "journal", support_dir=tmp_path / "support")

    for derived in (settings.index_path, settings.vectors_path, settings.internal_dir):
        assert not derived.is_relative_to(settings.data_dir), derived


def test_what_you_wrote_stays_in_the_journal(tmp_path: Path) -> None:
    """The persona is the one thing the app keeps that you authored, so it
    belongs with the entries — otherwise the journal folder stops being the
    whole record of what you made."""
    settings = Settings(data_dir=tmp_path / "journal", support_dir=tmp_path / "support")

    for authored in (settings.entries_dir, settings.brief_dir, settings.persona_path):
        assert authored.is_relative_to(settings.data_dir), authored


def test_the_support_directory_follows_the_platform() -> None:
    from tilt.config import default_support_dir

    where = default_support_dir()
    assert where.is_absolute()
    assert not where.is_relative_to(Path.home() / "Tilt"), "never inside a journal"


def test_the_persona_round_trips_as_readable_markdown(tmp_path: Path) -> None:
    """Markdown rather than JSON because every other file in that folder is
    readable, and a lone agent.json would be the exception."""
    from tilt.persona import PersonaStore, PersonaUpdate

    path = tmp_path / "agent.md"
    PersonaStore(path).update(PersonaUpdate(name="Vera", personality="Terse. Never flatters."))

    written = path.read_text()
    assert "name: Vera" in written
    assert "Terse. Never flatters." in written

    reloaded = PersonaStore(path).load()
    assert reloaded.name == "Vera"
    assert reloaded.personality == "Terse. Never flatters."


def test_a_persona_file_edited_into_nonsense_still_yields_an_agent(tmp_path: Path) -> None:
    """Losing the ability to reflect because someone mistyped YAML would be
    absurd — the agent must always have an identity to speak with."""
    from tilt.persona import DEFAULT_NAME, PersonaStore

    path = tmp_path / "agent.md"
    path.write_text("---\nname: [unclosed\n---\nwhatever\n")

    assert PersonaStore(path).load().name == DEFAULT_NAME


# ---------------------------------------------------------- somebody's key


class FakeVault:
    """A keychain that works, so the happy path is testable off macOS."""

    def __init__(self, *, works: bool = True) -> None:
        self.available = works
        self.held: str | None = None

    def get(self) -> str | None:
        return self.held

    def set(self, value: str) -> bool:
        if not self.available:
            return False
        self.held = value
        return True

    def clear(self) -> None:
        self.held = None


def test_the_key_goes_to_the_keychain_not_the_file(tmp_path: Path) -> None:
    """The whole point. A plaintext credential any process running as you can
    read was the real exposure, and this is what closes it."""
    path = tmp_path / "settings.json"
    vault = FakeVault()
    store = SettingsStore(path, vault=vault)

    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaSECRETVALUE"))

    assert vault.held == "AIzaSECRETVALUE"
    assert "AIzaSECRETVALUE" not in path.read_text(), "never in the file"
    assert store.load().gemini_api_key == "AIzaSECRETVALUE", "still usable"
    assert store.key_is_in_the_keychain is True


def test_the_non_secrets_stay_in_the_file(tmp_path: Path) -> None:
    """Only the key moves. The model, the ceiling and the feeds are not secret
    and are far easier to inspect and edit as a file."""
    path = tmp_path / "settings.json"
    store = SettingsStore(path, vault=FakeVault())

    store.update(
        RuntimeSettingsUpdate(
            gemini_api_key="AIzaSECRET", feeds=["https://ok.example/feed"]
        )
    )

    written = path.read_text()
    assert "ok.example" in written
    assert "AIzaSECRET" not in written


def test_upgrading_overwrites_the_plaintext_copy(tmp_path: Path) -> None:
    """Someone with a key already in settings.json must not be left with it
    sitting there after the key has moved to the keychain."""
    path = tmp_path / "settings.json"
    path.write_text('{"gemini_api_key": "AIzaOLDPLAINTEXT"}')
    vault = FakeVault()

    store = SettingsStore(path, vault=vault)
    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaOLDPLAINTEXT"))

    assert "AIzaOLDPLAINTEXT" not in path.read_text()
    assert vault.held == "AIzaOLDPLAINTEXT"


def test_no_keychain_falls_back_and_says_so(tmp_path: Path) -> None:
    """A container, CI, a headless box. The fallback is fine; being quiet about
    it is not — going from "encrypted by the OS" to "plain text on disk"
    without telling anyone is the objectionable part."""
    path = tmp_path / "journal" / "settings.json"
    key_path = tmp_path / "support" / "key.json"
    store = SettingsStore(path, key_path=key_path, vault=FakeVault(works=False))

    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaFALLBACK"))

    assert store.load().gemini_api_key == "AIzaFALLBACK", "the app still works"
    # Its own file, outside the journal. `settings.json` now lives beside the
    # entries so that feeds and the model travel with them, which makes it the
    # last place a live credential should be.
    assert "AIzaFALLBACK" in key_path.read_text()
    assert "AIzaFALLBACK" not in path.read_text()
    assert store.key_is_in_the_keychain is False
    assert key_path.stat().st_mode & 0o777 == 0o600


def test_the_status_route_names_where_the_key_is(client: TestClient) -> None:
    """So Settings can say something true rather than assume the stronger of
    the two. This box has no keychain, which is why it reads `file`."""
    assert client.get("/status").json()["key_storage"] in {"keychain", "file"}


def test_ephemeral_beats_both(tmp_path: Path) -> None:
    """A shared demo stores the key nowhere at all, and must not reach for a
    keychain it would then be leaving somebody else's credential in."""
    store = SettingsStore(tmp_path / "settings.json", ephemeral=True)

    assert store.vault is None, "never even probed"
    assert store.key_is_in_the_keychain is False


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


# ------------------------------------------------------- identity as a path


def test_an_id_that_is_not_a_filename_is_refused(tmp_path: Path) -> None:
    """The sink. An entry's id arrives from frontmatter — an import, a synced
    folder, a hand edit — and `path_for` interpolates it into a path, so an id
    carrying separators escapes the directory the write was meant for."""
    created = datetime(2026, 8, 7, 12, tzinfo=UTC)
    root = tmp_path / "entries"

    for hostile in ("../../../../../../evil", "a/b", "a\\b", "..", "", ".hidden"):
        with pytest.raises(ValueError):
            path_for(hostile, created, root)

    ordinary = path_for("01KZDYVGAFGA8J1R2X5159C5QZ", created, root)
    assert ordinary.resolve().is_relative_to(root.resolve())


def test_a_planted_id_costs_the_id_and_not_the_thought(tmp_path: Path) -> None:
    """The boundary, and the promise that survives it.

    Refusing to load the file would let anyone who can drop one into a synced
    folder hide an entry. It is indexed under its filename instead, and the
    substitution is reported the way two files claiming one id already are."""
    settings = Settings(
        data_dir=tmp_path / "journal",
        support_dir=tmp_path / "support",
        export_dir=tmp_path / "exports",
        provider="echo",
        schedule_enabled=False,
    )
    settings.ensure_dirs()
    entries = settings.entries_dir
    (entries / "2026" / "08").mkdir(parents=True)
    (entries / "2026" / "08" / "2026-08-07T120000Z-planted.md").write_text(
        "---\n"
        "id: '../../../../../../escaped'\n"
        "created: 2026-08-07T12:00:00+00:00\n"
        "updated: 2026-08-07T12:00:00+00:00\n"
        "kind: note\n"
        "provenance: self\n"
        "---\n"
        "a thought that must survive its own broken id\n",
        encoding="utf-8",
    )

    index = Index(settings.index_path)
    journal = Journal(settings.data_dir, index)
    try:
        assert journal.rebuild() == 1

        assert [r.declared for r in index.renamed_ids] == ["../../../../../../escaped"]
        used = index.renamed_ids[0].used
        assert index.get(used) is not None
        assert "must survive" in index.get(used).body

        # The unattended path: this is what the nightly folder pass calls, and
        # it is what used to land a file outside the journal.
        journal.set_themes(used, ["Somewhere"])

        outside = [
            p for p in tmp_path.rglob("*escaped*") if not p.is_relative_to(settings.data_dir)
        ]
        assert outside == []
    finally:
        index.close()


def test_a_source_id_cannot_name_a_file_outside_the_journal(tmp_path: Path) -> None:
    """`source_text_path` is the other interpolation, and it is both written
    and unlinked."""
    settings = Settings(
        data_dir=tmp_path / "journal",
        support_dir=tmp_path / "support",
        export_dir=tmp_path / "exports",
        provider="echo",
        schedule_enabled=False,
    )
    settings.ensure_dirs()
    index = Index(settings.index_path)
    journal = Journal(settings.data_dir, index)
    try:
        with pytest.raises(ValueError):
            journal.source_text_path("../../../../escaped")
        # Reading is an absence rather than an error, matching the other stores.
        assert journal.read_source_text("../../../../escaped") is None
    finally:
        index.close()


# ------------------------------------------- the gate and what it exempts


def test_a_suffix_does_not_open_the_gate(tmp_path: Path) -> None:
    """The exemption asks the static mount what it owns. It used to match on
    how the URL was spelled, so every route ending in a caller-supplied
    segment could be handed a `.png` and walk through."""
    with TestClient(create_app(interface(tmp_path))) as client:
        for path in (
            "/folders/pinned/anything.png",
            "/folders/declined/anything.svg",
            "/folders/refused/someid.svg?to=Elsewhere",
            "/entries/01KZDYVGAFGA8J1R2X5159C5QZ.png",
            "/nothing-of-the-sort.html",
        ):
            assert client.delete(path).status_code == 401, path
            assert client.get(path).status_code == 401, path

        # And the files the mount really has are still open, which is the
        # whole reason the exemption exists.
        assert client.get("/index.html").status_code == 200
        assert client.get("/assets/app.js").status_code == 200


def test_an_unauthenticated_caller_is_not_told_the_body_limit(tmp_path: Path) -> None:
    """The body limit sits inside the gate. Added the other way round it ran
    first, so an oversized request from nobody in particular was answered with
    a 413 naming the limit rather than a 401."""
    with TestClient(create_app(interface(tmp_path))) as client:
        response = client.post(
            "/entries",
            json={"body": "x"},
            headers={"Content-Length": str(MAX_REQUEST_BYTES + 1)},
        )
        assert response.status_code == 401


def test_only_a_real_preflight_skips_the_gate(tmp_path: Path) -> None:
    """Preflight carries no Authorization header by specification, so it has to
    be exempt. An ordinary OPTIONS is not a preflight and is not exempt."""
    with TestClient(create_app(interface(tmp_path))) as client:
        preflight = client.options(
            "/entries",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert preflight.status_code == 200
        assert client.options("/entries").status_code == 401


def test_the_served_page_carries_a_policy(tmp_path: Path) -> None:
    """The CSP in tauri.conf.json governs the webview. A browser loading the
    same page in the container got no policy at all, and could be framed."""
    with TestClient(create_app(interface(tmp_path))) as client:
        headers = client.get("/").headers
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["X-Content-Type-Options"] == "nosniff"


def test_the_desktop_app_is_not_given_page_headers(tmp_path: Path) -> None:
    """Nothing renders these there — the webview enforces its own policy — and
    a header on an API is noise that later reads as protection."""
    settings = Settings(
        data_dir=tmp_path,
        support_dir=tmp_path / "support",
        export_dir=tmp_path / "exports",
        auth_token="secret",
        schedule_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/status", headers={"Authorization": "Bearer secret"})
        assert "Content-Security-Policy" not in response.headers


# ------------------------------------------------- what the key is told about


def test_a_keychain_that_refuses_is_reported_as_a_file(tmp_path: Path) -> None:
    """The case the report exists for, and the one it used to get wrong.

    `key_is_in_the_keychain` answered from the presence of a backend, while
    `save` falls back to the file whenever the keychain *refuses* — locked,
    prompt dismissed, ACL denied. So a downgrade to a file mode was invisible,
    which is the opposite of what reporting it is for."""
    path = tmp_path / "settings.json"
    key_path = tmp_path / "support" / "key.json"
    vault = FakeVault(works=False)  # present, and refusing
    assert vault.available is False

    # A keychain that is there but says no on write.
    vault.available = True
    vault.set = lambda _value: False  # type: ignore[assignment]
    vault.get = lambda: None  # type: ignore[assignment]

    store = SettingsStore(path, key_path=key_path, vault=vault)
    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaREFUSEDBYKEYCHAIN"))

    assert key_path.exists(), "the key went to the file, as save intends"
    assert store.key_is_in_the_keychain is False, "and /status must say so"
    # And it must still be readable, rather than silently reading as empty and
    # dropping the app to offline.
    assert store.load().gemini_api_key == "AIzaREFUSEDBYKEYCHAIN"


def test_the_key_file_is_never_briefly_world_readable(tmp_path: Path) -> None:
    """The mode is the only thing protecting this file, so it is created at 600
    rather than created and then chmodded to it."""
    key_path = tmp_path / "support" / "key.json"
    store = SettingsStore(
        tmp_path / "settings.json", key_path=key_path, vault=FakeVault(works=False)
    )
    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaFILEMODE"))

    assert key_path.stat().st_mode & 0o777 == 0o600


def test_a_credential_spelled_as_a_field_is_redacted_too() -> None:
    """The denylist matched `key=` query parameters. An SDK that echoes back
    the body it sent spells the same thing as a JSON field."""
    leaky = '{"model": "gemini-3-flash", "api_key": "AIzaSyC7fake_KEY_material99"}'

    clean = redact(leaky)

    assert "AIzaSyC7fake_KEY_material99" not in clean
    # Which credential was rejected is the diagnostic worth keeping.
    assert "api_key" in clean
    assert "gemini-3-flash" in clean


# ------------------------------------------------- one journal, one instance


def test_a_second_instance_is_refused(tmp_path: Path) -> None:
    """Two Tilts on one journal is not hypothetical: the installed app hides
    rather than quits, and `tauri dev` reads the same folder, so the ordinary
    way to try a change runs a second copy over the first.

    SQLite arbitrates its own writers, so the damage is not a corrupt database
    — it is two schedulers doing the same unattended work, and an entry's
    frontmatter read-modify-written by both with one write simply lost."""
    settings = Settings(
        data_dir=tmp_path / "journal",
        support_dir=tmp_path / "support",
        export_dir=tmp_path / "exports",
        provider="echo",
        schedule_enabled=False,
    )
    settings.ensure_dirs()

    first = hold_journal(settings)
    assert first is not None, "POSIX, so there is a lock to take"

    with pytest.raises(SystemExit) as refused:
        hold_journal(settings)
    assert str(settings.data_dir) in str(refused.value)

    # Released when the holder goes, which is why this is a lock and not a pid
    # file: a Tilt that crashed leaves nothing to clean up.
    first.close()
    second = hold_journal(settings)
    assert second is not None
    second.close()


def test_a_different_journal_is_not_blocked(tmp_path: Path) -> None:
    """The claim is on a journal, not on the application."""
    def settings_for(name: str) -> Settings:
        return Settings(
            data_dir=tmp_path / name,
            support_dir=tmp_path / f"{name}-support",
            export_dir=tmp_path / "exports",
            provider="echo",
            schedule_enabled=False,
        )

    one, two = settings_for("first"), settings_for("second")
    one.ensure_dirs()
    two.ensure_dirs()

    held_one = hold_journal(one)
    held_two = hold_journal(two)
    assert held_one is not None and held_two is not None
    held_one.close()
    held_two.close()
