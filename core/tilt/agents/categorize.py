"""Categorisation — the agent files your thought so you never have to.

Produces tags and assigns the entry to a theme, reusing an existing theme
whenever one fits. Themes are what the sidebar browses: folders you did not
create and do not maintain.
"""

from __future__ import annotations

from tilt.agents.ledger import MeteredProvider
from tilt.agents.parsing import clean_label, clean_tags, extract_json, snap
from tilt.journal import Journal
from tilt.models import Entry, EntryKind, EntryUpdate, TagCount, Theme, utcnow
from tilt.store.files import new_id

JOB = "categorize"

THEME_CONTEXT = 40
"""Folders shown to the model, busiest first.

Bounded so the prompt stays a fixed cost as the journal grows, and because the
tail of a long folder list is the part nothing is ever filed into anyway."""

TAG_CONTEXT = 60
"""Tags shown, commonest first. The long tail is deliberately withheld: showing
a model six hundred tags used once each teaches it that inventing tags is what
one does here."""

SYSTEM = """You file thoughts in a private journal called Tilt.

You are given one entry and the vocabulary this journal already uses. Respond
with JSON only — no prose, no code fence:

{"tags": ["...", "..."], "theme": "Theme Name", "reason": "one short clause"}

The vocabulary is the point. A journal where every entry invented its own
folder and its own tags has categorised nothing — it has restated each entry in
fewer words. Your job is to place this entry among the ones already here, and
to extend the vocabulary only when it genuinely does not reach.

Rules:
- "theme": reuse an existing theme name EXACTLY, character for character, when
  one is even roughly right. Invent one only when the entry belongs to none of
  them — not when it belongs to one imperfectly. An entry that is an awkward
  fit for an existing folder still goes in that folder.
- A new theme name is 1-3 words, Title Case, and names a lasting area of
  interest rather than this single entry. If you would not expect another
  twenty entries to land under it within a year, it is too specific.
- Never propose themes named after activities or tasks. Themes are subjects of
  thought, not things to do.
- 2 to 4 tags, lowercase. Reuse tags from the list wherever they apply, in
  preference to a more precise new one — a tag used once will never group
  anything, and grouping is the only thing a tag is for.
- No generic tags: "thoughts", "ideas", "personal", "note", "misc".
- Prefer nouns and noun phrases the writer would recognise as their own."""


def build_prompt(
    entry: Entry,
    existing: list[Theme],
    body: str | None = None,
    tags: list[TagCount] | None = None,
) -> str:
    """The entry, and the vocabulary it is being placed among.

    The tag list used to be absent entirely, which made the instruction to
    reuse tags unfollowable: the model was told to prefer existing tags while
    being shown none of them, so every entry invented its own and the sidebar
    filled with words used exactly once.
    """
    themes = (
        "\n".join(f"- {t.label} ({t.count} entries)" for t in existing[:THEME_CONTEXT])
        or "(none yet)"
    )
    seen = (
        ", ".join(f"{t.tag} ({t.count})" for t in (tags or [])[:TAG_CONTEXT])
        or "(none yet)"
    )
    return (
        f"TASK: categorize\n\nEXISTING THEMES:\n{themes}\n\n"
        f"TAGS ALREADY IN USE:\n{seen}\n\nENTRY:\n{body or entry.body}"
    )


def _filing_text(journal: Journal, entry: Entry) -> str:
    """What to file this entry on.

    Its own words, except for a source — whose body is a filename and a summary
    of itself. Filing on that produced folders called "Talk" and "Paper" and
    tags like "sentences": the entry was categorised by its packaging rather
    than by anything in it. The ideas pulled out of it are its content, so a
    source is filed on those and the packaging is left out entirely.

    A source with no ideas in it yet falls back to its body — better a folder
    named after a filename than no folder at all.
    """
    if entry.kind is not EntryKind.SOURCE:
        return entry.body
    cards = journal.index.children([entry.id]).get(entry.id, [])
    ideas = "\n".join(c.body for c in cards).strip()
    return ideas or entry.body


async def categorize(
    journal: Journal,
    provider: MeteredProvider,
    entry_id: str,
    *,
    interactive: bool = True,
) -> Entry | None:
    """Tag an entry and slot it into a theme.

    Returns the updated entry, or ``None`` when it does not exist. A response
    that cannot be parsed leaves the entry untouched rather than clearing tags
    it already had.
    """
    entry = journal.get(entry_id)
    if entry is None:
        return None

    existing = journal.index.themes()
    seen = journal.index.tags()
    completion = await provider.complete(
        build_prompt(entry, existing, _filing_text(journal, entry), seen),
        job=JOB,
        system=SYSTEM,
        interactive=interactive,
    )

    # Recorded on the strength of the call having returned, not on it having
    # produced tags. A response the parser could not use is this model's answer
    # for this entry, and paying for the same answer again every night is worse
    # than leaving one thought untagged.
    journal.mark_considered(entry_id, filed=True)

    payload = extract_json(completion.text)
    if not isinstance(payload, dict):
        return entry

    # Snapping runs after the prompt has already asked for reuse, because asking
    # is not a mechanism. A model that returns "attention economy" when
    # "attention" is right there has not been disobedient — it has been
    # slightly more precise than is useful — and the sidebar is what pays for
    # the precision. Tags snap more readily than folders: a tag is a label, a
    # folder is a place, and merging two places wrongly loses a distinction.
    vocabulary = [t.tag for t in seen]
    tags = [
        snap(tag, vocabulary, threshold=0.86) or tag
        for tag in clean_tags(payload.get("tags"))
    ]
    if tags:
        journal.update(entry_id, EntryUpdate(tags=list(dict.fromkeys(tags))))

    label = clean_label(payload.get("theme"))
    if label:
        label = snap(label, [t.label for t in existing]) or label
        now = utcnow()
        theme = journal.index.upsert_theme(
            Theme(
                id=new_id(),
                label=label,
                description=str(payload.get("reason") or "")[:200],
                created=now,
                updated=now,
            )
        )
        if theme:
            journal.index.set_entry_themes(entry_id, [theme.id])
            # Also written to the entry's frontmatter, so folder membership
            # survives losing the index.
            journal.set_themes(entry_id, [theme.label])

    return journal.get(entry_id)
