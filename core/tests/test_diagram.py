"""Diagram this.

Mermaid is a parser being handed model output, so most of what is tested here is
what does *not* survive the trip: a diagram may describe your thinking, but it
has no business opening pages or reconfiguring the renderer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tilt.agents.base import Completion, Pricing
from tilt.agents.diagram import DiagramError, extract_mermaid, repair
from tilt.agents.ledger import MeteredProvider
from tilt.journal import Journal
from tilt.models import Artifact, EntryCreate, Theme, utcnow
from tilt.store.artifacts import ArtifactStore
from tilt.store.files import new_id

# ------------------------------------------------------------------ sanitising


def test_a_plain_diagram_passes_through() -> None:
    source = 'flowchart TD\n  A["Attention"] --> B["Filtering"]'
    assert extract_mermaid(source) == source


def test_a_code_fence_is_unwrapped() -> None:
    """The prompt says not to add one. It sometimes does anyway, and refusing an
    otherwise good diagram over three backticks would be pedantry."""
    assert extract_mermaid('```mermaid\nmindmap\n  root((Ideas))\n```').startswith("mindmap")


def test_prose_around_the_diagram_is_dropped() -> None:
    text = (
        "Here is the diagram you asked for:\n\n"
        "```\nflowchart LR\n  A --> B\n```\n\nHope it helps!"
    )
    assert extract_mermaid(text) == "flowchart LR\n  A --> B"


def test_a_click_directive_never_survives() -> None:
    # `click` binds a node to a URL or a callback. Nothing about describing
    # someone's thinking requires the diagram to be able to navigate.
    out = extract_mermaid(
        'flowchart TD\n  A["Attention"]\n  click A "https://example.com" _blank'
    )
    assert "click" not in out
    assert 'A["Attention"]' in out


def test_an_href_never_survives() -> None:
    out = extract_mermaid('flowchart TD\n  A["x"]\n  A-->B\n  click B href "javascript:void(0)"')
    assert "href" not in out.lower()


def test_an_init_block_never_survives() -> None:
    """`%%{init}%%` rewrites the renderer's configuration from inside the
    document — including its security level, which is the setting that stops
    everything else here from mattering."""
    out = extract_mermaid(
        '%%{init: {"securityLevel": "loose"}}%%\nflowchart TD\n  A --> B'
    )
    assert "init" not in out
    assert out.startswith("flowchart")


def test_a_multiline_init_block_never_survives() -> None:
    out = extract_mermaid('%%{\n  init: {\n    "theme": "x"\n  }\n}%%\nmindmap\n  root((A))')
    assert "theme" not in out


def test_something_that_is_not_a_diagram_is_refused() -> None:
    # Rendering prose is not a thing to attempt. Saying so beats handing the
    # parser an essay and reporting whatever it complains about.
    with pytest.raises(DiagramError, match="did not come back as a diagram"):
        extract_mermaid("I'm sorry, I can't draw that.")


def test_an_unknown_diagram_type_is_refused() -> None:
    """An allowlist, not a denylist. Mermaid keeps adding diagram types, and a
    new one appearing in training data should not become a new thing the
    renderer will attempt because nobody thought about it."""
    with pytest.raises(DiagramError):
        extract_mermaid("gitGraph\n  commit")


def test_an_empty_response_is_refused() -> None:
    with pytest.raises(DiagramError):
        extract_mermaid("")


# ------------------------------------------------------------------ the store


def test_a_diagram_survives_losing_the_index(settings, index) -> None:
    """The whole reason diagrams are files and not rows.

    ``index.db`` is a disposable cache the app is willing to throw away; a
    diagram that lived only in it would be paid work destroyed by a rebuild."""
    store = ArtifactStore(settings.diagrams_dir)
    saved = store.save(
        Artifact(
            id=new_id(),
            kind="mindmap",
            title="Attention",
            body="mindmap\n  root((Attention))",
            note="grouped by what recurs",
            subject_ids=["a", "b"],
            created=utcnow(),
        )
    )

    index.close()
    settings.index_path.unlink()

    back = ArtifactStore(settings.diagrams_dir).all()
    assert [a.id for a in back] == [saved.id]
    assert back[0].body == "mindmap\n  root((Attention))"
    assert back[0].subject_ids == ["a", "b"]
    assert back[0].note == "grouped by what recurs"


def test_repairing_replaces_the_broken_draft(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "diagrams")
    broken = store.save(
        Artifact(id="D1", kind="flowchart", body="flowchart TD\n  A -->", created=utcnow())
    )
    store.save(broken.model_copy(update={"body": "flowchart TD\n  A --> B"}))

    assert len(store.all()) == 1, "a draft that did not render is not worth keeping"
    assert store.load("D1").body == "flowchart TD\n  A --> B"


def test_a_hand_broken_file_costs_only_itself(tmp_path) -> None:
    root = tmp_path / "diagrams"
    root.mkdir(parents=True)
    (root / "good.md").write_text("---\nid: good\nkind: mindmap\n---\nmindmap\n")
    (root / "bad.md").write_text("---\nid: [unclosed\n---\nnope\n")

    assert [a.id for a in ArtifactStore(root).all()] == ["good"]


def test_deleting_says_whether_there_was_anything_to_delete(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "diagrams")
    store.save(Artifact(id="D1", kind="mindmap", body="mindmap\n", created=utcnow()))
    assert store.delete("D1") is True
    assert store.delete("D1") is False


# ----------------------------------------------------------------- the repair


class _Twice:
    """Broken first, valid on the repair — the shape the round trip exists for."""

    name = "double"
    follows_references = False
    pricing = Pricing(input_per_m=0.0, output_per_m=0.0)

    def __init__(self, second: str) -> None:
        self.second = second
        self.calls = 0

    async def complete(self, prompt: str, **_: object) -> Completion:
        self.calls += 1
        return Completion(text=self.second, model="double", tokens_in=1, tokens_out=1)


@pytest.mark.anyio
async def test_a_repair_keeps_the_id_and_takes_the_error(journal: Journal, index) -> None:
    provider = MeteredProvider(
        _Twice('{"title": "Fixed", "kind": "flowchart", "mermaid": "flowchart TD\\n A --> B"}'),
        index,
        ceiling_usd=1.0,
    )
    broken = Artifact(
        id="D1", kind="flowchart", title="Attention", body="flowchart TD\n A -->",
        created=utcnow(),
    )
    fixed = await repair(
        journal, provider, artifact=broken, entries=[], error="Parse error on line 2"
    )

    assert fixed.id == "D1", "the repair replaces the draft rather than joining it"
    assert fixed.body == "flowchart TD\n A --> B"


@pytest.mark.anyio
async def test_a_repair_that_fails_again_raises_rather_than_looping(
    journal: Journal, index
) -> None:
    """Two failures is enough evidence that the model cannot draw this one. A
    third paid attempt is a loop, not a fix."""
    provider = MeteredProvider(
        _Twice('{"mermaid": "I still cannot draw this."}'), index, ceiling_usd=1.0
    )
    broken = Artifact(id="D1", kind="flowchart", body="flowchart TD\n A -->", created=utcnow())
    with pytest.raises(DiagramError):
        await repair(journal, provider, artifact=broken, entries=[], error="Parse error")


# ---------------------------------------------------------------- the endpoint


def _seed(client: TestClient) -> Theme:
    journal: Journal = client.app.state.journal
    now = utcnow()
    theme = journal.index.upsert_theme(
        Theme(id=new_id(), label="Attention", created=now, updated=now)
    )
    for body in (
        "Attention behaves like a filter rather than a spotlight.",
        "Attention discards most of what arrives, and the discarding is the work.",
        "The spotlight metaphor makes attention sound additive.",
    ):
        entry = journal.create(EntryCreate(body=body))
        journal.index.set_entry_themes(entry.id, [theme.id])
    return theme


def test_drawing_a_folder_saves_something_that_parses_as_mermaid(
    client: TestClient,
) -> None:
    theme = _seed(client)
    body = client.post("/diagram", json={"theme_id": theme.id}).json()

    assert body["kind"] == "mindmap"
    assert body["body"].startswith("mindmap")
    assert body["path"], "a diagram that was not written down is not a diagram"
    assert len(body["subject_ids"]) == 3

    assert [a["id"] for a in client.get("/diagrams").json()] == [body["id"]]


def test_the_offline_note_says_it_did_not_read_anything(client: TestClient) -> None:
    # Offline this is word grouping, not comprehension, and a diagram that
    # looked considered would be the most misleading thing in the app.
    theme = _seed(client)
    note = client.post("/diagram", json={"theme_id": theme.id}).json()["note"]
    assert "Offline" in note


def test_drawing_everything_is_refused_with_a_reason(client: TestClient) -> None:
    response = client.post("/diagram", json={})
    assert response.status_code == 400
    assert "no shape to find" in response.json()["detail"]


def test_drawing_a_folder_that_is_gone_is_a_404(client: TestClient) -> None:
    assert client.post("/diagram", json={"theme_id": "nope"}).status_code == 404


def test_drawing_an_empty_search_says_there_is_nothing_there(client: TestClient) -> None:
    response = client.post("/diagram", json={"q": "nothing matches this"})
    assert response.status_code == 422
    assert "nothing here to draw" in response.json()["detail"]


def test_a_diagram_can_be_deleted(client: TestClient) -> None:
    theme = _seed(client)
    made = client.post("/diagram", json={"theme_id": theme.id}).json()

    assert client.delete(f"/diagrams/{made['id']}").status_code == 204
    assert client.get("/diagrams").json() == []
    assert client.delete(f"/diagrams/{made['id']}").status_code == 404


def test_repairing_something_that_does_not_exist_is_a_404(client: TestClient) -> None:
    response = client.post("/diagram/nope/repair", json={"error": "Parse error"})
    assert response.status_code == 404
