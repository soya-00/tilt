"""Themes, tags, and links — the structures the sidebar navigates."""

from __future__ import annotations

import pytest

from tilt.agents.categorize import categorize
from tilt.agents.connect import _settle_kind, connect
from tilt.agents.ledger import MeteredProvider
from tilt.agents.parsing import clean_label, clean_tags, extract_json
from tilt.journal import Journal
from tilt.models import (
    Entry,
    EntryCreate,
    Link,
    LinkKind,
    LinkRecord,
    Provenance,
    Theme,
    utcnow,
)
from tilt.store import files
from tilt.store.files import new_id
from tilt.store.index import Index, pair_key


def _theme(label: str) -> Theme:
    now = utcnow()
    return Theme(id=new_id(), label=label, created=now, updated=now)


# ------------------------------------------------------------------- parsing


def test_extract_json_from_a_fenced_response() -> None:
    """Models wrap JSON in fences no matter how the prompt is worded."""
    raw = 'Sure!\n```json\n{"tags": ["memory"], "theme": "Memory"}\n```\nHope that helps.'
    assert extract_json(raw) == {"tags": ["memory"], "theme": "Memory"}


def test_extract_json_handles_braces_inside_strings() -> None:
    assert extract_json('{"rationale": "uses a { brace"}') == {"rationale": "uses a { brace"}


def test_extract_json_returns_none_when_absent() -> None:
    assert extract_json("no json here at all") is None
    assert extract_json("") is None


def test_clean_tags_lowercases_and_deduplicates() -> None:
    # "Attention" and "attention" arriving on different days must not split
    # one idea across two sidebar rows.
    assert clean_tags(["Attention", "#attention", "  MEMORY  "]) == ["attention", "memory"]


def test_clean_tags_rejects_non_lists_and_caps_length() -> None:
    assert clean_tags("attention") == []
    assert len(clean_tags([f"tag{i}" for i in range(20)])) == 5


def test_clean_label_titlecases() -> None:
    assert clean_label("  attention and focus ") == "Attention And Focus"
    assert clean_label("") == ""
    assert clean_label(None) == ""


# -------------------------------------------------------------------- themes


def test_upsert_theme_reuses_an_existing_label_case_insensitively(index: Index) -> None:
    first = index.upsert_theme(_theme("Attention"))
    second = index.upsert_theme(_theme("attention"))

    assert first.id == second.id
    assert len(index.themes()) == 1


def test_renaming_a_theme_pins_it_against_the_agent(index: Index) -> None:
    theme = index.upsert_theme(_theme("Attention"))
    index.rename_theme(theme.id, "How I Pay Attention")

    # The agent proposing the old label again must not undo the rename.
    index.upsert_theme(_theme("Attention"))
    assert index.get_theme(theme.id).label == "How I Pay Attention"


def test_theme_counts_reflect_membership(journal: Journal) -> None:
    theme = journal.index.upsert_theme(_theme("Memory"))
    for i in range(3):
        entry = journal.create(EntryCreate(body=f"Thought {i}."))
        journal.index.set_entry_themes(entry.id, [theme.id])

    assert journal.index.themes()[0].count == 3


def test_prune_removes_empty_themes(index: Index) -> None:
    index.upsert_theme(_theme("Orphan"))
    assert index.prune_empty_themes() == 1
    assert index.themes() == []


def test_deleting_a_theme_keeps_every_entry_in_it(journal: Journal) -> None:
    """The point of the control. A folder is the agent's opinion about your
    writing; deleting it must discard the opinion and nothing else."""
    theme = journal.index.upsert_theme(_theme("Attention"))
    entries = [journal.create(EntryCreate(body=f"Thought {i}.")) for i in range(3)]
    for entry in entries:
        journal.index.set_entry_themes(entry.id, [theme.id])

    assert journal.delete_theme(theme.id) is True

    assert journal.index.themes() == []
    for entry in entries:
        assert journal.get(entry.id) is not None
        assert journal.thread(entry.id).themes == []


def test_deleting_a_theme_leaves_an_entry_s_other_folders_alone(journal: Journal) -> None:
    keep = journal.index.upsert_theme(_theme("Memory"))
    drop = journal.index.upsert_theme(_theme("Attention"))
    entry = journal.create(EntryCreate(body="Filed under both."))
    journal.index.set_entry_themes(entry.id, [keep.id, drop.id])

    journal.delete_theme(drop.id)

    assert [t.label for t in journal.thread(entry.id).themes] == ["Memory"]


def test_a_deleted_theme_does_not_come_back_on_rebuild(journal: Journal) -> None:
    """Themes are restored from each entry's own Markdown at boot. A delete
    that only touched SQLite would resurrect the folder on the next start,
    which is the failure mode this rewrite exists to prevent."""
    theme = journal.index.upsert_theme(_theme("Attention"))
    entry = journal.create(EntryCreate(body="A thought about attention."))
    journal.index.set_entry_themes(entry.id, [theme.id])
    journal.set_themes(entry.id, ["Attention"])

    journal.delete_theme(theme.id)
    journal.rebuild()

    assert journal.index.themes() == []


def test_deleting_a_theme_that_does_not_exist_reports_it(journal: Journal) -> None:
    assert journal.delete_theme("nope") is False


# ---------------------------------------------------------------------- tags


def test_tag_histogram_excludes_replies(journal: Journal) -> None:
    from tilt.models import EntryUpdate, ReplyKind

    a = journal.create(EntryCreate(body="One.", tags=["memory", "attention"]))
    journal.create(EntryCreate(body="Two.", tags=["memory"]))
    reply = journal.add_reply(a.id, "A reflection.", ReplyKind.REFLECTION)
    journal.update(reply.id, EntryUpdate(tags=["memory"]))

    counts = {t.tag: t.count for t in journal.index.tags()}
    assert counts == {"memory": 2, "attention": 1}


# --------------------------------------------------------------------- links


def test_pair_key_is_order_independent() -> None:
    assert pair_key("a", "b") == pair_key("b", "a")


def test_a_pair_can_only_be_judged_once(journal: Journal) -> None:
    a = journal.create(EntryCreate(body="First."))
    b = journal.create(EntryCreate(body="Second."))

    def link(src: str, dst: str) -> Link:
        return Link(
            id=new_id(), src_id=src, dst_id=dst, kind=LinkKind.ECHO,
            rationale="r", created=utcnow(),
        )

    assert journal.index.add_link(link(a.id, b.id)) is True
    # The reverse direction is the same pair and must be refused.
    assert journal.index.add_link(link(b.id, a.id)) is False


def test_links_surface_on_both_entries(journal: Journal) -> None:
    a = journal.create(EntryCreate(body="First."))
    b = journal.create(EntryCreate(body="Second."))
    journal.index.add_link(
        Link(id=new_id(), src_id=a.id, dst_id=b.id, kind=LinkKind.ECHO,
             rationale="shared idea", created=utcnow())
    )

    links = journal.index.links_for([a.id, b.id])
    assert links[a.id][0][1].id == b.id, "a should point at b"
    assert links[b.id][0][1].id == a.id, "and b back at a"


def test_link_fields_survive_the_join(journal: Journal) -> None:
    """`SELECT l.*, e.*` would let the entry's id and created overwrite the
    link's; every link column is aliased to prevent that."""
    a = journal.create(EntryCreate(body="First."))
    b = journal.create(EntryCreate(body="Second."))
    link_id = new_id()
    journal.index.add_link(
        Link(id=link_id, src_id=a.id, dst_id=b.id, kind=LinkKind.BRIDGE,
             rationale="a real rationale", created=utcnow())
    )

    link, other = journal.index.links_for([a.id])[a.id][0]
    assert link.id == link_id
    assert link.id != other.id
    assert link.kind is LinkKind.BRIDGE
    assert link.rationale == "a real rationale"


def test_dismissed_links_are_hidden_but_still_block_reproposal(journal: Journal) -> None:
    a = journal.create(EntryCreate(body="First."))
    b = journal.create(EntryCreate(body="Second."))
    link_id = new_id()
    journal.index.add_link(
        Link(id=link_id, src_id=a.id, dst_id=b.id, kind=LinkKind.ECHO,
             rationale="r", created=utcnow())
    )

    assert journal.index.dismiss_link(link_id) is True
    assert journal.index.links_for([a.id])[a.id] == []
    assert b.id in journal.index.judged_pairs(a.id), "a dismissal must be permanent"


def test_a_dismissal_survives_losing_the_index(journal: Journal) -> None:
    """Permanent has to mean permanent, and the index is disposable.

    A dismissal written only to SQLite lasts until someone deletes index.db.
    The link would come back on the next rebuild, the pair would drop out of
    judged_pairs, and the connector would pay to reach the same verdict again.
    """
    a = journal.create(EntryCreate(body="Attention is a filter."))
    b = journal.create(EntryCreate(body="Memory is reconstruction."))
    link_id = new_id()
    journal.index.add_link(
        Link(id=link_id, src_id=a.id, dst_id=b.id, kind=LinkKind.ECHO,
             rationale="both about the mind", created=utcnow())
    )
    journal.record_link(a.id, LinkRecord(to=b.id, kind="echo", why="both about the mind"))

    assert journal.dismiss_link(link_id) is True
    journal.rebuild()

    assert journal.index.links_for([a.id])[a.id] == []
    assert b.id in journal.index.judged_pairs(a.id)


def test_dismissing_a_link_that_does_not_exist_reports_it(journal: Journal) -> None:
    assert journal.dismiss_link("nope") is False


# ----------------------------------------------------------- agents, offline


async def test_categorize_assigns_tags_and_a_theme(
    journal: Journal, provider: MeteredProvider
) -> None:
    entry = journal.create(
        EntryCreate(body="Attention behaves like a filter. Attention discards most input.")
    )
    updated = await categorize(journal, provider, entry.id)

    assert updated.tags, "tags should be assigned"
    thread = journal.thread(entry.id)
    assert len(thread.themes) == 1


async def test_categorize_reuses_an_existing_theme(
    journal: Journal, provider: MeteredProvider
) -> None:
    first = journal.create(EntryCreate(body="Attention is a filter on attention."))
    await categorize(journal, provider, first.id)
    second = journal.create(EntryCreate(body="More on attention and how attention works."))
    await categorize(journal, provider, second.id)

    assert len(journal.index.themes()) == 1, "should file into the existing theme"


async def test_categorize_on_missing_entry_returns_none(
    journal: Journal, provider: MeteredProvider
) -> None:
    assert await categorize(journal, provider, "nope") is None


def test_reading_someone_you_disagree_with_is_not_contradicting_yourself() -> None:
    """A source arguing the other way is a counterpoint, not a self-contradiction.

    Exploring an opposing view is how a position gets tested. Labelling it as
    the writer disagreeing with themself is both wrong and a reason to read
    less widely, so the model's word is not taken on it.
    """
    mine = Entry(id=new_id(), created=utcnow(), updated=utcnow(), body="Attention is a filter.")
    read = Entry(
        id=new_id(),
        created=utcnow(),
        updated=utcnow(),
        provenance=Provenance.SOURCE,
        body="Attention is better understood as a spotlight.",
    )

    assert _settle_kind(LinkKind.CONTRADICTION, mine, read) is LinkKind.COUNTERPOINT
    assert _settle_kind(LinkKind.CONTRADICTION, read, mine) is LinkKind.COUNTERPOINT


def test_disagreeing_with_your_own_earlier_self_stays_a_contradiction() -> None:
    """The case the word is reserved for. Noticing a changed mind is the point."""
    then = Entry(id=new_id(), created=utcnow(), updated=utcnow(), body="Attention is a filter.")
    now = Entry(id=new_id(), created=utcnow(), updated=utcnow(), body="No — it is a spotlight.")

    assert _settle_kind(LinkKind.CONTRADICTION, now, then) is LinkKind.CONTRADICTION


def test_other_link_kinds_are_left_alone_whatever_the_provenance() -> None:
    mine = Entry(id=new_id(), created=utcnow(), updated=utcnow(), body="A thought.")
    read = Entry(
        id=new_id(), created=utcnow(), updated=utcnow(), provenance=Provenance.SOURCE, body="Read."
    )
    for kind in (LinkKind.ECHO, LinkKind.ELABORATION, LinkKind.BRIDGE):
        assert _settle_kind(kind, mine, read) is kind


async def test_connect_links_entries_sharing_concepts(
    journal: Journal, provider: MeteredProvider
) -> None:
    journal.create(
        EntryCreate(body="Memory is reconstructive; every recall rewrites the memory.")
    )
    later = journal.create(
        EntryCreate(body="Recall rewrites memory, so memory is reconstructive rather than stored.")
    )

    links = await connect(journal, provider, later.id)
    assert len(links) == 1
    assert links[0].rationale


async def test_connect_stays_silent_on_unrelated_entries(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Silence is the correct and common answer; a noisy connector is the
    fastest way to lose trust."""
    journal.create(EntryCreate(body="Sourdough needs a wetter starter in winter."))
    later = journal.create(EntryCreate(body="Kestrels hover by pinning their heads still."))

    assert await connect(journal, provider, later.id) == []


async def test_connect_never_repeats_a_judged_pair(
    journal: Journal, provider: MeteredProvider
) -> None:
    journal.create(EntryCreate(body="Memory is reconstructive; recall rewrites memory."))
    later = journal.create(EntryCreate(body="Recall rewrites memory; memory is reconstructive."))

    assert len(await connect(journal, provider, later.id)) == 1
    assert await connect(journal, provider, later.id) == [], "already judged"


async def test_folders_and_links_survive_a_rebuild(
    journal: Journal, provider: MeteredProvider
) -> None:
    """The bug this exists to prevent: rebuild() ran on every boot, and
    entry_themes/links cascade from entries, so restarting the app silently
    destroyed every folder assignment and connection the agent had made."""
    first = journal.create(
        EntryCreate(body="Memory is reconstructive; every recall rewrites the memory.")
    )
    await categorize(journal, provider, first.id)
    second = journal.create(
        EntryCreate(body="Recall rewrites memory, so memory is reconstructive not stored.")
    )
    await categorize(journal, provider, second.id)
    assert await connect(journal, provider, second.id) != []

    themes_before = {t.label: t.count for t in journal.index.themes()}
    links_before = len(journal.index.all_links())
    assert links_before > 0

    journal.rebuild()

    assert {t.label: t.count for t in journal.index.themes()} == themes_before
    assert len(journal.index.all_links()) == links_before


async def test_structure_returns_after_the_index_is_deleted(
    settings, journal: Journal, provider: MeteredProvider
) -> None:
    """Frontmatter is the durable copy: throw the database away entirely and
    folders and connections still come back."""
    a = journal.create(EntryCreate(body="Attention is a filter that discards most input."))
    await categorize(journal, provider, a.id)
    b = journal.create(EntryCreate(body="Attention discards; the filter model of attention."))
    await categorize(journal, provider, b.id)
    await connect(journal, provider, b.id)

    expected_themes = {t.label for t in journal.index.themes()}
    expected_links = len(journal.index.all_links())

    journal.index.close()
    settings.index_path.unlink()

    fresh = Index(settings.index_path)
    rebuilt = Journal(settings.data_dir, fresh)
    rebuilt.rebuild()

    assert {t.label for t in fresh.themes()} == expected_themes
    assert len(fresh.all_links()) == expected_links
    fresh.close()


async def test_connect_on_an_empty_journal_is_a_noop(
    journal: Journal, provider: MeteredProvider
) -> None:
    only = journal.create(EntryCreate(body="The very first thought."))
    assert await connect(journal, provider, only.id) == []


@pytest.mark.parametrize("bad", ["", "not json", '{"links": "nope"}'])
async def test_connect_survives_unusable_model_output(
    journal: Journal, index: Index, bad: str
) -> None:
    from tilt.agents.base import Completion, Pricing

    class Garbage:
        name = "garbage"
        pricing = Pricing(0.0, 0.0)

        async def complete(self, prompt: str, *, system: str | None = None) -> Completion:
            return Completion(text=bad, model="garbage")

    journal.create(EntryCreate(body="An earlier thought about memory."))
    entry = journal.create(EntryCreate(body="A later thought about memory."))
    metered = MeteredProvider(Garbage(), index, ceiling_usd=1.0)

    assert await connect(journal, metered, entry.id) == []


def test_a_rename_survives_losing_the_index(journal: Journal, settings) -> None:
    """Folders are rebuilt from each entry's own Markdown on boot, so a rename
    confined to SQLite lasts until the next restart — and then the old name is
    recreated from the frontmatter that still carries it, the entries follow it
    back, and the renamed folder is left standing empty beside it."""
    entry = journal.create(EntryCreate(body="Attention is a budget."))
    now = utcnow()
    theme = journal.index.upsert_theme(
        Theme(id=new_id(), label="Attention", created=now, updated=now)
    )
    journal.index.set_entry_themes(entry.id, [theme.id])
    journal.set_themes(entry.id, [theme.label])

    assert journal.rename_theme(theme.id, "Personal Computing") is not None
    journal.rebuild()

    labels = [t.label for t in journal.index.themes()]
    assert labels == ["Personal Computing"], f"the old folder came back: {labels}"
    # Read from the file, not the index: the index has no column for folder
    # membership, and the file is the copy the rebuild will read next time.
    on_disk = files.parse(journal.index.path_of(entry.id))
    assert on_disk.theme_labels == ["Personal Computing"]


def test_renaming_something_that_is_gone_changes_nothing(journal: Journal) -> None:
    assert journal.rename_theme("nope", "Whatever") is None
