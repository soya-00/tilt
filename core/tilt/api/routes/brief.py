"""The brief — reading that has not happened yet, from either side.

Four things you can do: see what is there, put something there yourself, read
one, or say no to one. There is no "complete" and no ordering to maintain,
because this is not a queue of work — it is a shelf, and a shelf with three
things on it that have sat there a month is not failing at anything.

The read path is one call into :func:`tilt.api.routes.ingest._distil`, which is
the same code the paste box and the file upload go through. Reusing it is the
whole point: a finding the scout proposed and a link you pasted yourself become
the same kind of entry, judged by the same promotion bar, with no second path
that could quietly behave differently.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from tilt.agents.base import Reference
from tilt.agents.ledger import MeteredProvider
from tilt.agents.scout import snap_tags
from tilt.api.deps import get_brief, get_journal, get_persona_store, get_provider
from tilt.api.routes.ingest import _distil
from tilt.ingest import Medium, classify
from tilt.journal import Journal
from tilt.models import BriefItem, BriefOrigin, Thread, utcnow
from tilt.persona import PersonaStore
from tilt.store.brief import BriefStore, normalise
from tilt.store.files import new_id

router = APIRouter(prefix="/brief", tags=["brief"])


class AddRequest(BaseModel):
    url: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=200)
    why: str = Field(default="", max_length=1000)
    """Optional, and worth filling in. A link with no note is unreadable to you
    a fortnight later — the reason you saved it is the first thing to go."""
    tags: list[str] = Field(default_factory=list, max_length=8)
    """Typed inline as ``#tags`` and parsed out by the composer. Snapped
    against the journal's existing vocabulary here rather than there, so the
    rule holds whoever is calling — a typo lands on the tag you meant."""


@router.get("", response_model=list[BriefItem])
def list_brief(brief: BriefStore = Depends(get_brief)) -> list[BriefItem]:
    """Everything waiting, newest first. Dismissed items stay out of sight."""
    return brief.all()


@router.post("", response_model=BriefItem, status_code=status.HTTP_201_CREATED)
def add_to_brief(
    payload: AddRequest,
    brief: BriefStore = Depends(get_brief),
    journal: Journal = Depends(get_journal),
) -> BriefItem:
    """Put something here yourself.

    Takes a URL, a note, or both — a plain note with no link is a legitimate
    item, because "read the second half of that book" is a thing you meant to
    do and there is no address for it.

    Adding something already here returns what is already here rather than a
    duplicate or an error. You saved it twice because you forgot, and the
    honest response to that is to show you that you had not.
    """
    url = payload.url.strip()
    title = payload.title.strip()
    why = " ".join(payload.why.split())

    if not url and not why and not title:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Nothing to add. A link, a title, or a note — any one will do.",
        )

    if url:
        key = normalise(url)
        for existing in brief.all(include_dismissed=True):
            if normalise(existing.url) == key:
                # Undismiss on the way past: putting something back yourself
                # overrides a no the scout recorded, or one you gave it before
                # you had a reason to care.
                if existing.dismissed:
                    return brief.save(existing.model_copy(update={"dismissed": False}))
                return existing

    # No title is invented from the URL. The slug of a magazine article comes
    # out as "the shallows", which reads as a title someone typed badly rather
    # than as an address — the view shows the host instead, which is at least
    # true.
    return brief.save(
        BriefItem(
            id=new_id(),
            title=title,
            url=url or None,
            why=why,
            origin=BriefOrigin.YOU,
            tags=snap_tags(payload.tags, [t.tag for t in journal.index.tags()]),
            created=utcnow(),
        )
    )


@router.post("/{item_id}/read", response_model=Thread)
async def read_item(
    item_id: str,
    brief: BriefStore = Depends(get_brief),
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    personas: PersonaStore = Depends(get_persona_store),
) -> Thread:
    """Read one, and let it become an entry.

    This is the only expensive call in the whole feature, and it is the only
    one behind a decision a person made. The scout gathering and triaging costs
    a fraction of a cent a day precisely so that this — distillation, the most
    expensive call in the app — never happens unasked.

    The item is removed rather than tombstoned on success: it is in the journal
    now, and ``entries.source_url`` remembers it better than a dead file here
    would.
    """
    item = brief.load(item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not in the brief.")
    if not item.url:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This is a note to yourself, not a link. There is nothing to read for you.",
        )

    route = classify(url=item.url, text="")
    if route.medium not in (Medium.VIDEO, Medium.ARTICLE):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That link is not something Tilt can read. Paste the text instead.",
        )
    if not provider.follows_references:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "Reading a link needs a Gemini key. Add one in Settings, or paste the text.",
        )

    source = await _distil(
        journal,
        provider,
        personas,
        title=item.title or route.title,
        text="",
        url=item.url,
        reference=Reference(url=route.url or item.url, kind=route.medium.value),
    )
    # Only after the entry exists. A distillation that failed at the ceiling or
    # at the provider must leave the item where it was, or a budget stop would
    # silently eat something you asked for.
    brief.remove(item_id)
    return journal.thread(source.id)


@router.post("/{item_id}/dismiss", response_model=BriefItem)
def dismiss_item(item_id: str, brief: BriefStore = Depends(get_brief)) -> BriefItem:
    """No, and do not offer this again.

    A tombstone rather than a deletion, for the scout's sake — it has to know
    what it has already put in front of you, or it proposes the same paper
    every morning until you stop opening the list.
    """
    item = brief.dismiss(item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not in the brief.")
    return item
