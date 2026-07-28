"""Runtime settings, the agent persona, and source distillation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tilt.agents.distill import MAX_CHARS, _window, distill
from tilt.agents.ledger import MeteredProvider
from tilt.journal import Journal
from tilt.models import EntryKind, Provenance
from tilt.persona import Persona, PersonaStore, PersonaUpdate
from tilt.settings_store import RuntimeSettingsUpdate, SettingsStore

# --------------------------------------------------------------------- persona


def test_persona_round_trips_to_disk(tmp_path) -> None:
    store = PersonaStore(tmp_path / "agent.json")
    store.update(PersonaUpdate(name="Neo", personality="Warm but exacting."))

    # A fresh store over the same file: this is what a restart looks like.
    assert PersonaStore(tmp_path / "agent.json").load().name == "Neo"


def test_persona_falls_back_rather_than_raising(tmp_path) -> None:
    path = tmp_path / "agent.json"
    path.write_text("{ this is not json", encoding="utf-8")
    # The agent must always have an identity to speak with.
    assert PersonaStore(path).load().name == "Tilt"


def test_persona_reaches_the_prompt() -> None:
    from tilt.agents.reflect import system_prompt

    prompt = system_prompt(Persona(name="Neo", personality="Warm but exacting."))
    assert 'Your name is "Neo"' in prompt
    assert "Warm but exacting." in prompt


def test_empty_name_falls_back_to_the_default(tmp_path) -> None:
    store = PersonaStore(tmp_path / "agent.json")
    assert store.update(PersonaUpdate(name="   ")).name == "Tilt"


# -------------------------------------------------------------------- settings


def test_settings_never_return_the_key(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaSECRETVALUE9999"))

    public = store.public()
    assert public.has_key is True
    assert public.key_hint == "…9999"
    # The key itself must never be serialisable back out through the API.
    assert "SECRET" not in public.model_dump_json()


def test_settings_survive_a_restart(tmp_path) -> None:
    SettingsStore(tmp_path / "settings.json").update(
        RuntimeSettingsUpdate(gemini_api_key="AIzaABC", gemini_model="gemini-3.5-flash")
    )
    reloaded = SettingsStore(tmp_path / "settings.json").load()
    assert reloaded.gemini_api_key == "AIzaABC"
    assert reloaded.gemini_model == "gemini-3.5-flash"


def test_blank_key_field_does_not_wipe_an_existing_key(tmp_path) -> None:
    """An empty field in the UI means 'leave it alone', never 'clear it'."""
    store = SettingsStore(tmp_path / "settings.json")
    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaKEEPME"))
    store.update(RuntimeSettingsUpdate(gemini_model="gemini-3.6-flash"))
    assert store.load().gemini_api_key == "AIzaKEEPME"


def test_settings_endpoints(client: TestClient) -> None:
    assert client.get("/settings").json()["has_key"] is False

    saved = client.patch("/settings", json={"gemini_api_key": "AIzaTESTKEY4321"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["key_hint"] == "…4321"


def test_persona_endpoints(client: TestClient) -> None:
    updated = client.patch("/agent/persona", json={"name": "Neo", "personality": "Terse."})
    assert updated.json() == {"name": "Neo", "personality": "Terse."}
    assert client.get("/agent/persona").json()["name"] == "Neo"


# --------------------------------------------------------------------- distill


def test_window_keeps_both_ends_of_a_long_source() -> None:
    """A transcript's thesis is at the front and its conclusion at the back;
    the middle is the expendable part."""
    text = "START " + ("filler " * 20_000) + " FINISH"
    windowed = _window(text)

    assert len(windowed) < len(text)
    assert windowed.startswith("START")
    assert windowed.endswith("FINISH")
    assert "omitted" in windowed


def test_window_leaves_short_text_alone() -> None:
    assert _window("a short source") == "a short source"


async def test_distill_creates_one_source_with_nested_cards(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Ingesting a transcript must never flood the Stream: one entry, cards
    nested beneath it."""
    text = (
        "The core claim is that attention is a filter, not a spotlight. "
        "Everything arrives at the senses and most of it is discarded before awareness. "
        "What you notice feels chosen but is mostly the residue of discarding. "
    ) * 20

    source = await distill(journal, provider, title="A talk on attention", text=text)

    assert source is not None
    assert source.kind is EntryKind.SOURCE
    assert source.provenance is Provenance.SOURCE

    thread = journal.thread(source.id)
    assert len(thread.replies) > 0, "cards should be nested under the source"
    assert all(c.provenance is Provenance.SOURCE for c in thread.replies)

    # One top-level item, not one per card: the source appears once in the
    # Stream and none of its cards surface as roots of their own.
    roots = journal.stream()
    assert sum(1 for t in roots if t.entry.id == source.id) == 1
    card_ids = {c.id for c in thread.replies}
    assert not card_ids & {t.entry.id for t in roots}


async def test_distill_preserves_the_full_text_on_disk(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Only a window goes to the model; the original must survive intact."""
    text = "Unique marker phrase. " + ("body text. " * 6000) + "Closing marker phrase."
    assert len(text) > MAX_CHARS

    source = await distill(journal, provider, title="Long", text=text)
    stored = journal.read_source_text(source.id)

    assert stored == text
    assert "Unique marker phrase." in stored
    assert "Closing marker phrase." in stored


async def test_distill_rejects_empty_input(journal: Journal, provider: MeteredProvider) -> None:
    assert await distill(journal, provider, title="", text="   ") is None


def test_ingest_endpoint_returns_the_thread(client: TestClient) -> None:
    text = ("Attention is a filter rather than a spotlight, discarding most input. ") * 15
    response = client.post("/ingest", json={"title": "Talk", "text": text})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entry"]["kind"] == "source"


def test_ingest_rejects_something_absurdly_large(client: TestClient) -> None:
    response = client.post("/ingest", json={"title": "Huge", "text": "x" * 2_100_000})
    assert response.status_code == 413
