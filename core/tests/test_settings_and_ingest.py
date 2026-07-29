"""Runtime settings, the agent persona, and source distillation."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from tilt.agents.distill import MAX_CHARS, _window, distill
from tilt.agents.ledger import MeteredProvider
from tilt.jobs.sweep import sweep
from tilt.journal import Journal
from tilt.models import EntryCreate, EntryKind, Provenance, utcnow
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


def test_feeds_round_trip_through_the_api(client: TestClient) -> None:
    """The scout is only worth pointing somewhere if you can point it. Feeds go
    out in the clear, unlike the key — they are addresses of public pages, and
    hiding them would mean nobody could tell what was being watched."""
    saved = client.patch(
        "/settings", json={"feeds": ["https://example.com/feed.xml", "  "]}
    )

    assert saved.json()["feeds"] == ["https://example.com/feed.xml"]
    assert client.get("/settings").json()["feeds"] == ["https://example.com/feed.xml"]


def test_a_feed_must_be_an_http_url(tmp_path) -> None:
    """A file:// or data: URL here would point the scout at the machine it runs
    on, which is not what "watch a publication" means to anyone typing it."""
    store = SettingsStore(tmp_path / "settings.json")

    store.update(
        RuntimeSettingsUpdate(
            feeds=[
                "file:///etc/passwd",
                "javascript:alert(1)",
                "https://ok.example/feed",
                "https://ok.example/feed",
            ]
        )
    )

    assert store.load().feeds == ["https://ok.example/feed"]


def test_saving_a_key_leaves_the_feeds_alone(tmp_path) -> None:
    """Every field the UI does not send has to survive the ones it does."""
    store = SettingsStore(tmp_path / "settings.json")
    store.update(RuntimeSettingsUpdate(feeds=["https://ok.example/feed"]))

    store.update(RuntimeSettingsUpdate(gemini_api_key="AIzaABC"))

    assert store.load().feeds == ["https://ok.example/feed"]


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


def _settle(journal: Journal) -> None:
    """Age everything past the sweep's quiet period.

    Ingest writes its cards in the same instant the test asks for them, and the
    sweep deliberately ignores anything that new. Nothing else about the
    behaviour under test depends on the clock.
    """
    when = (utcnow() - timedelta(hours=1)).isoformat()
    journal.index._conn.execute("UPDATE entries SET created = ?", (when,))
    journal.index._conn.commit()


async def test_an_idea_from_a_source_can_meet_something_you_wrote(
    journal: Journal, provider: MeteredProvider
) -> None:
    """The reason to ingest anything at all.

    An extracted idea that never joins the graph is a nicer bookmark. This is
    a talk answering a question you asked yourself months earlier.
    """
    mine = journal.create(
        EntryCreate(body="Memory is reconstructive; every recall rewrites the memory.")
    )
    journal.mark_considered(mine.id, filed=True, judged=True)

    text = "Recall rewrites memory, so memory is reconstructive rather than stored. " * 8
    source = await distill(journal, provider, title="A talk on memory", text=text)
    _settle(journal)

    await sweep(journal, provider)

    linked = {
        other.id
        for card in journal.index.children([source.id])[source.id]
        for _, other in journal.index.links_for([card.id]).get(card.id, [])
    }
    assert mine.id in linked, "an idea from the source should have found the earlier thought"


async def test_a_card_is_never_filed_into_one_of_your_folders(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Folders describe your preoccupations. Filing borrowed material into them
    dilutes every one of them."""
    text = "Attention is a filter that discards most of what reaches it. " * 8
    source = await distill(journal, provider, title="A talk", text=text)
    _settle(journal)

    await sweep(journal, provider)

    cards = journal.index.children([source.id])[source.id]
    assert cards, "the source should have produced at least one card"
    for card in cards:
        assert journal.index.themes_for([card.id])[card.id] == []


async def test_two_ideas_from_the_same_source_are_not_a_discovery(
    journal: Journal, provider: MeteredProvider
) -> None:
    """They sat next to each other in one argument before Tilt ever saw them.
    Proposing that as a connection is noise, and it is not free."""
    text = (
        "Attention is a filter that discards most input. "
        "Memory is reconstructive and rewrites itself on every recall. "
    ) * 8
    source = await distill(journal, provider, title="A talk", text=text)
    cards = journal.index.children([source.id])[source.id]
    assert len(cards) >= 2, "need at least two cards for this to mean anything"

    siblings = {c.id for c in cards}
    assert not siblings & {c.id for c in journal.context_for(cards[0].id)}


async def test_an_empty_journal_promotes_everything(
    journal: Journal, provider: MeteredProvider
) -> None:
    """There is nothing to be relevant to yet. Filtering the first source you
    ever add down to silence is not a bar, it is a broken feature."""
    text = "Attention is a filter that discards most input. " * 10
    source = await distill(journal, provider, title="A talk", text=text)

    thread = journal.thread(source.id)
    assert thread.replies, "the first ingest must show something"
    assert thread.quiet == 0


async def test_a_source_unrelated_to_your_writing_stays_quiet(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Ingesting is meant to be filtering. A source that meets nothing you
    think should leave the Stream almost untouched."""
    journal.create(EntryCreate(body="Memory is reconstructive; recall rewrites the memory."))
    journal.create(EntryCreate(body="Recall rewrites memory rather than replaying it."))

    text = (
        "Sourdough needs a wetter starter through the winter months. "
        "Cold flour slows fermentation more than most bakers expect. "
    ) * 10
    source = await distill(journal, provider, title="On bread", text=text)

    thread = journal.thread(source.id)
    assert thread.quiet > 0, "none of this speaks to what they write about"
    assert thread.entry.id, "the source itself still appears in the Stream"


async def test_a_quiet_card_is_still_findable(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Quiet is not deleted. Not clearing the bar means it is not pushed at
    you — going looking for it must still work."""
    journal.create(EntryCreate(body="Memory is reconstructive; recall rewrites the memory."))
    text = "Cold flour slows fermentation more than most bakers expect. " * 10
    source = await distill(journal, provider, title="On bread", text=text)

    quiet = [c for c in journal.index.children([source.id])[source.id] if not c.promoted]
    assert quiet, "this source should have produced something quiet"

    found = {e.id for e in journal.search("fermentation")}
    assert found & {c.id for c in quiet}


async def test_the_bar_survives_a_rebuild(journal: Journal, provider: MeteredProvider) -> None:
    """Promotion lives in frontmatter like everything else the agent decides.
    A rebuild that forgot it would dump every quiet card into the Stream."""
    journal.create(EntryCreate(body="Memory is reconstructive; recall rewrites the memory."))
    text = "Cold flour slows fermentation more than most bakers expect. " * 10
    source = await distill(journal, provider, title="On bread", text=text)
    before = journal.thread(source.id).quiet
    assert before > 0

    journal.rebuild()

    assert journal.thread(source.id).quiet == before


async def test_a_source_is_filed_by_its_ideas_not_by_its_filename(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Found by looking at the sidebar: folders called "Talk" and "Paper".

    A source entry's body is a filename and a summary of itself, so filing on
    it categorises the packaging. The ideas pulled out of it are its content.
    """
    text = (
        "Attention is a filter that discards most of what arrives. "
        "What reaches awareness is the residue of that discarding. "
    ) * 8
    source = await distill(journal, provider, title="talk", text=text)
    _settle(journal)

    await sweep(journal, provider)

    labels = [t.label for t in journal.thread(source.id).themes]
    assert labels, "a source should still be filed somewhere"
    assert "Talk" not in labels, "filed by its own filename"
    assert not (set(source.tags) & {"talk", "sentences", "candidate"})


async def test_the_source_entry_itself_is_never_judged(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Its body is a title and a summary — a container, not a thought.

    Found by running it: two unrelated sources were linked to each other on the
    word "extract", which appeared only in the summaries the app had written
    about them. The ideas inside a source are the atoms worth judging.
    """
    journal.create(EntryCreate(body="Attention is a filter that discards most input."))
    first = await distill(journal, provider, title="A talk", text="Attention discards. " * 20)
    second = await distill(journal, provider, title="A paper", text="Memory rewrites. " * 20)
    _settle(journal)

    await sweep(journal, provider)

    for source in (first, second):
        assert journal.index.links_for([source.id])[source.id] == []


async def test_a_card_is_never_paired_with_the_source_it_came_out_of(
    journal: Journal, provider: MeteredProvider
) -> None:
    text = "Attention is a filter that discards most input. " * 10
    source = await distill(journal, provider, title="A talk", text=text)
    card = journal.index.children([source.id])[source.id][0]

    assert source.id not in {c.id for c in journal.context_for(card.id)}


async def test_deleting_a_source_takes_its_stored_text_with_it(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Otherwise the transcript outlives everything that could reach it.

    The entry goes, its cards cascade, and a full transcript stays behind in
    sources/ that nothing can search, show, or ever delete.
    """
    source = await distill(journal, provider, title="Talk", text="A thought. " * 40)
    stored = journal.source_text_path(source.id)
    assert stored.exists()

    assert journal.delete(source.id) is True
    assert not stored.exists()


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
