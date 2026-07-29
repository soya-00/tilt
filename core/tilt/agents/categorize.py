"""Categorisation — the agent files your thought so you never have to.

Produces tags and assigns the entry to a theme, reusing an existing theme
whenever one fits. Themes are what the sidebar browses: folders you did not
create and do not maintain.
"""

from __future__ import annotations

from tilt.agents.ledger import MeteredProvider
from tilt.agents.parsing import clean_label, clean_tags, extract_json
from tilt.journal import Journal
from tilt.models import Entry, EntryKind, EntryUpdate, Theme, utcnow
from tilt.store.files import new_id

JOB = "categorize"

SYSTEM = """You file thoughts in a private journal called Tilt.

Given one entry and the list of themes that already exist, respond with JSON
only — no prose, no code fence:

{"tags": ["...", "..."], "theme": "Theme Name", "reason": "one short clause"}

Rules:
- 2 to 4 tags. Lowercase. Concepts the writer is actually working with, not
  generic labels like "thoughts", "ideas", "personal", or "note".
- Prefer nouns and noun phrases the writer would recognise as their own.
- For "theme": reuse an existing theme name EXACTLY when one genuinely fits.
  Only invent a new one when the entry belongs to none of them.
- A new theme name is 1-3 words, Title Case, and describes a lasting area of
  interest rather than this single entry.
- Never propose themes named after activities or tasks. Themes are subjects of
  thought, not things to do."""


def build_prompt(entry: Entry, existing: list[Theme], body: str | None = None) -> str:
    themes = (
        "\n".join(f"- {t.label} ({t.count} entries)" for t in existing[:40])
        or "(none yet)"
    )
    return f"TASK: categorize\n\nEXISTING THEMES:\n{themes}\n\nENTRY:\n{body or entry.body}"


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
    completion = await provider.complete(
        build_prompt(entry, existing, _filing_text(journal, entry)),
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

    tags = clean_tags(payload.get("tags"))
    if tags:
        journal.update(entry_id, EntryUpdate(tags=tags))

    label = clean_label(payload.get("theme"))
    if label:
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
