"""The constellation query.

The graph is the first surface that shows the journal as a shape rather than a
sequence, and the failures worth testing are all failures of honesty: drawing
something that is not a thought, drawing an edge to a node that is not there, or
capping the view without saying so.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tilt.journal import Journal
from tilt.models import (
    EntryCreate,
    EntryKind,
    Link,
    LinkKind,
    Provenance,
    ReplyKind,
    Theme,
    utcnow,
)
from tilt.store.files import new_id


def _link(journal: Journal, src: str, dst: str, kind: LinkKind = LinkKind.ECHO) -> None:
    journal.index.add_link(
        Link(
            id=new_id(),
            src_id=src,
            dst_id=dst,
            kind=kind,
            rationale="both turn on attention",
            created=utcnow(),
        )
    )


def _theme(journal: Journal, label: str, entry_ids: list[str]) -> Theme:
    now = utcnow()
    theme = journal.index.upsert_theme(
        Theme(id=new_id(), label=label, created=now, updated=now)
    )
    assert theme is not None
    for entry_id in entry_ids:
        journal.index.set_entry_themes(entry_id, [theme.id])
    return theme


# ------------------------------------------------------------------ what draws


def test_replies_are_never_nodes(journal: Journal) -> None:
    """A reflection is something the app said about a thought, not a second one.

    Drawing both would double the graph and pair every entry with a node that
    only ever says what the entry already says."""
    entry = journal.create(EntryCreate(body="Attention is a budget."))
    journal.add_reply(entry.id, "What would change your mind?", ReplyKind.REFLECTION)

    drawn = journal.index.graph_entries(limit=50)
    assert [e.id for e in drawn] == [entry.id]


def test_sources_are_off_until_asked_for(journal: Journal) -> None:
    mine = journal.create(EntryCreate(body="Attention is a budget."))
    read = journal.create(
        EntryCreate(
            body="A talk on distraction.",
            kind=EntryKind.SOURCE,
            provenance=Provenance.SOURCE,
        )
    )

    assert [e.id for e in journal.index.graph_entries(limit=50)] == [mine.id]
    both = {e.id for e in journal.index.graph_entries(limit=50, include_sources=True)}
    assert both == {mine.id, read.id}


def test_demoted_cards_stay_out_of_the_graph(journal: Journal) -> None:
    """A card that did not clear the promotion bar is quiet everywhere.

    It is still indexed and still searchable — but the graph is a picture of
    what you are thinking about, and an idea the bar rejected is not that."""
    source = journal.create(
        EntryCreate(
            body="A talk.", kind=EntryKind.SOURCE, provenance=Provenance.SOURCE
        )
    )
    loud = journal.add_card(
        source_id=source.id, body="Attention is a budget.", promoted=True
    )
    journal.add_card(
        source_id=source.id,
        body="The speaker thanks the organisers.",
        promoted=False,
    )

    drawn = journal.index.graph_entries(limit=50, include_sources=True)
    assert loud.id in {e.id for e in drawn}
    assert len(drawn) == 2, "the source and its promoted card, not the quiet one"


def test_a_theme_filter_restricts_the_graph(journal: Journal) -> None:
    inside = journal.create(EntryCreate(body="Attention is a budget."))
    journal.create(EntryCreate(body="Unrelated thought about bread."))
    theme = _theme(journal, "Attention", [inside.id])

    drawn = journal.index.graph_entries(limit=50, theme_id=theme.id)
    assert [e.id for e in drawn] == [inside.id]


# ------------------------------------------------------------------- the edges


def test_an_edge_needs_both_ends_present(journal: Journal) -> None:
    """An edge to a filtered-out node has nothing to attach to.

    Force layouts either drop it silently or invent a phantom node for it, and
    a node the user cannot click is worse than a missing line."""
    mine = journal.create(EntryCreate(body="Attention is a budget."))
    read = journal.create(
        EntryCreate(
            body="A talk on distraction.",
            kind=EntryKind.SOURCE,
            provenance=Provenance.SOURCE,
        )
    )
    other = journal.create(EntryCreate(body="Distraction is expensive."))
    _link(journal, mine.id, read.id)
    _link(journal, mine.id, other.id)

    # Sources excluded: only the self-to-self link survives.
    mine_only = journal.index.graph_entries(limit=50)
    edges = journal.index.links_between([e.id for e in mine_only])
    assert {(e.src_id, e.dst_id) for e in edges} == {(mine.id, other.id)}

    both = journal.index.graph_entries(limit=50, include_sources=True)
    assert len(journal.index.links_between([e.id for e in both])) == 2


def test_dismissed_links_are_not_drawn(journal: Journal) -> None:
    a = journal.create(EntryCreate(body="First."))
    b = journal.create(EntryCreate(body="Second."))
    _link(journal, a.id, b.id)
    link_id = journal.index.all_links()[0].id
    journal.dismiss_link(link_id)

    assert journal.index.links_between([a.id, b.id]) == []


def test_links_between_an_empty_set_asks_nothing(journal: Journal) -> None:
    """An empty IN () is a syntax error in SQLite, not an empty result."""
    assert journal.index.links_between([]) == []


# --------------------------------------------------------------------- the cap


def test_the_cap_keeps_the_newest_and_says_so(journal: Journal) -> None:
    made = [journal.create(EntryCreate(body=f"Thought {n}.")) for n in range(5)]

    drawn = journal.index.graph_entries(limit=2)
    assert [e.id for e in drawn] == [made[4].id, made[3].id]
    assert journal.index.graph_count() == 5


def test_the_count_uses_the_same_filter_as_the_rows(journal: Journal) -> None:
    """Otherwise the view says "showing 1 of 2" about entries it could never
    have drawn under that filter."""
    journal.create(EntryCreate(body="Mine."))
    journal.create(
        EntryCreate(
            body="Read.", kind=EntryKind.SOURCE, provenance=Provenance.SOURCE
        )
    )
    assert journal.index.graph_count() == 1
    assert journal.index.graph_count(include_sources=True) == 2


# ----------------------------------------------------------------- the endpoint


@pytest.fixture
def seeded(client: TestClient) -> dict:
    """A journal with two connected thoughts filed under one folder."""
    journal: Journal = client.app.state.journal
    a = journal.create(EntryCreate(body="Attention is a budget.\nSecond line."))
    b = journal.create(EntryCreate(body="Distraction is the interest on it."))
    _link(journal, a.id, b.id, LinkKind.ELABORATION)
    theme = _theme(journal, "Attention", [a.id, b.id])
    return {"a": a, "b": b, "theme": theme}


def test_graph_returns_entries_themes_and_both_edge_kinds(
    client: TestClient, seeded: dict
) -> None:
    graph = client.get("/graph").json()

    kinds = {n["id"]: n["kind"] for n in graph["nodes"]}
    assert kinds[seeded["a"].id] == "note"
    assert kinds[seeded["theme"].id] == "theme"

    edge_kinds = sorted(e["kind"] for e in graph["edges"])
    assert edge_kinds == ["elaboration", "member", "member"]
    assert graph["truncated"] is False
    assert graph["total"] == 2


def test_a_node_is_labelled_by_its_opening_line(
    client: TestClient, seeded: dict
) -> None:
    """A node has to be recognisable from across the canvas, and the opening
    line is how people remember what they wrote."""
    graph = client.get("/graph").json()
    label = next(n["label"] for n in graph["nodes"] if n["id"] == seeded["a"].id)
    assert label == "Attention is a budget."


def test_a_long_line_is_trimmed_rather_than_wrapped(client: TestClient) -> None:
    journal: Journal = client.app.state.journal
    journal.create(EntryCreate(body="A " + "very " * 40 + "long thought."))

    label = client.get("/graph").json()["nodes"][0]["label"]
    assert len(label) <= 48
    assert label.endswith("…")


def test_a_heading_is_not_a_label(client: TestClient) -> None:
    journal: Journal = client.app.state.journal
    journal.create(EntryCreate(body="## On attention\n\nIt is a budget."))
    assert client.get("/graph").json()["nodes"][0]["label"] == "On attention"


def test_theme_weight_counts_only_the_entries_drawn(
    client: TestClient, seeded: dict
) -> None:
    """A node whose size disagrees with the number of lines touching it reads
    as a rendering bug."""
    graph = client.get("/graph?limit=1").json()
    theme = next(n for n in graph["nodes"] if n["kind"] == "theme")
    assert theme["weight"] == 1
    assert graph["truncated"] is True
    assert graph["total"] == 2


def test_folders_can_be_left_out(client: TestClient, seeded: dict) -> None:
    graph = client.get("/graph?include_themes=false").json()
    assert all(n["kind"] != "theme" for n in graph["nodes"])
    assert all(e["kind"] != "member" for e in graph["edges"])


def test_the_graph_carries_the_rationale_for_each_connection(
    client: TestClient, seeded: dict
) -> None:
    """Hovering an edge should say why the agent drew it. Without the sentence
    the graph is a claim with no argument behind it."""
    graph = client.get("/graph").json()
    edge = next(e for e in graph["edges"] if e["kind"] == "elaboration")
    assert edge["rationale"] == "both turn on attention"


def test_an_empty_journal_draws_nothing_without_failing(client: TestClient) -> None:
    graph = client.get("/graph").json()
    assert graph == {"nodes": [], "edges": [], "truncated": False, "total": 0}
