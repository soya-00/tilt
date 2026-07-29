"""Keeping the sidebar a vocabulary rather than a list.

Folders and tags are only worth having if there are few enough of them to
recognise. Left alone a model mints "Attention", "Attentional Control" and
"Attention Economy" across three nights, each with one member, and the sidebar
becomes an index of things written once. The prompt asks for reuse; these are
the parts that do not depend on asking.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tilt.agents.categorize import build_prompt
from tilt.agents.parsing import canonical, snap
from tilt.journal import Journal
from tilt.models import Entry, EntryCreate, TagCount, Theme, utcnow
from tilt.store.files import new_id

# ------------------------------------------------------------------- canonical


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Attention", "attention"),
        ("Attention", "  attention  "),
        ("memories", "memory"),
        ("Boxes", "box"),
        ("personal computing", "Personal Computing"),
        ("self-talk", "self talk"),
    ],
)
def test_terms_that_are_not_actually_different(a: str, b: str) -> None:
    """Case, punctuation and plurality are not distinctions anyone makes on
    purpose, and each one costs a row of the sidebar."""
    assert canonical(a) == canonical(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("memory", "memoir"),
        ("attention", "intention"),
        ("bread", "dread"),
        ("physics", "physical"),
    ],
)
def test_terms_that_only_look_alike(a: str, b: str) -> None:
    assert canonical(a) != canonical(b)


def test_canonical_of_nothing_is_nothing() -> None:
    assert canonical("   ") == ""
    assert canonical("!!!") == ""


# ------------------------------------------------------------------------ snap


def test_a_plural_snaps_to_the_singular_already_in_use() -> None:
    assert snap("Memories", ["Memory", "Attention"]) == "Memory"


def test_case_alone_never_creates_a_second_folder() -> None:
    assert snap("attention", ["Attention"]) == "Attention"


def test_a_near_miss_snaps_to_what_it_meant() -> None:
    assert snap("attentional", ["attention"], threshold=0.86) == "attention"


def test_a_genuinely_new_subject_is_left_alone() -> None:
    # The whole point is to be conservative. Sourdough is not attention.
    assert snap("Sourdough", ["Attention", "Memory"]) is None


def test_a_phrase_never_snaps_onto_one_of_its_words() -> None:
    """"Memory" and "Memory And Attention" score well above any useful
    threshold and are not the same folder — the second is a claim about the
    first meeting something else."""
    assert snap("Memory And Attention", ["Memory"]) is None
    assert snap("Memory", ["Memory And Attention"]) is None


def test_the_closest_match_wins_when_several_are_near() -> None:
    assert snap("attentions", ["attention", "attentive"], threshold=0.8) == "attention"


def test_snapping_returns_the_existing_spelling_not_the_proposed_one() -> None:
    """The existing term is the one already written into other entries'
    frontmatter. Returning the proposal would rename the folder from under
    every entry already filed in it."""
    assert snap("personal computing", ["Personal Computing"]) == "Personal Computing"


def test_an_empty_vocabulary_snaps_to_nothing() -> None:
    assert snap("Attention", []) is None


# ---------------------------------------------------------------- the prompt


def _entry() -> Entry:
    now = utcnow()
    return Entry(id=new_id(), created=now, updated=now, body="Attention is a budget.")


def test_the_prompt_shows_the_tags_already_in_use() -> None:
    """This was the whole bug. The model was told to prefer existing tags while
    being shown none of them, so every entry invented its own."""
    now = utcnow()
    prompt = build_prompt(
        _entry(),
        [Theme(id="t", label="Attention", created=now, updated=now, count=3)],
        None,
        [TagCount(tag="attention", count=4), TagCount(tag="memory", count=2)],
    )
    assert "TAGS ALREADY IN USE" in prompt
    assert "attention (4)" in prompt
    assert "memory (2)" in prompt


def test_the_prompt_says_so_when_there_is_no_vocabulary_yet() -> None:
    prompt = build_prompt(_entry(), [], None, [])
    assert "(none yet)" in prompt


# ------------------------------------------------------------------ end to end


def test_filing_reuses_a_folder_rather_than_minting_a_near_duplicate(
    client: TestClient,
) -> None:
    journal: Journal = client.app.state.journal
    now = utcnow()
    journal.index.upsert_theme(
        Theme(id=new_id(), label="Memory", created=now, updated=now)
    )
    # "Memory" is not a substring of "memories", so the offline provider cannot
    # reuse the folder by the string match it normally relies on. It proposes
    # "Memories" instead, which is exactly the near-duplicate snapping is for —
    # without it this test ends with two folders holding one entry each.
    entry = journal.create(
        EntryCreate(body="Memories rewrite themselves. Memories are reconstructive.")
    )

    response = client.post("/agent/categorize", json={"entry_id": entry.id})
    assert response.status_code == 200

    labels = [t.label for t in journal.index.themes()]
    assert labels == ["Memory"], f"a second near-identical folder appeared: {labels}"
