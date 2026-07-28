"""Entry and stream endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from tilt.api.deps import get_journal
from tilt.journal import Journal
from tilt.models import Entry, EntryCreate, EntryUpdate, Thread

router = APIRouter(prefix="/entries", tags=["entries"])


@router.get("", response_model=list[Thread])
def list_stream(
    limit: int = Query(50, ge=1, le=200),
    before: str | None = Query(None, description="ISO timestamp for keyset pagination"),
    theme_id: str | None = Query(None, description="Scope to one agent-created theme"),
    tag: str | None = Query(None, description="Scope to one tag"),
    journal: Journal = Depends(get_journal),
) -> list[Thread]:
    return journal.stream(limit=limit, before=before, theme_id=theme_id, tag=tag)


@router.post("", response_model=Thread, status_code=status.HTTP_201_CREATED)
def create_entry(payload: EntryCreate, journal: Journal = Depends(get_journal)) -> Thread:
    if not payload.body.strip():
        # Literal 422 rather than the starlette constant, whose name is in the
        # middle of a deprecation rename across versions.
        raise HTTPException(422, "Entry body is empty.")
    entry = journal.create(payload)
    return Thread(entry=entry, replies=[])


@router.get("/search", response_model=list[Entry])
def search_entries(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    journal: Journal = Depends(get_journal),
) -> list[Entry]:
    return journal.search(q, limit=limit)


@router.get("/{entry_id}", response_model=Thread)
def get_thread(entry_id: str, journal: Journal = Depends(get_journal)) -> Thread:
    thread = journal.thread(entry_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    return thread


@router.patch("/{entry_id}", response_model=Entry)
def update_entry(
    entry_id: str, payload: EntryUpdate, journal: Journal = Depends(get_journal)
) -> Entry:
    entry = journal.update(entry_id, payload)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_id: str, journal: Journal = Depends(get_journal)) -> None:
    if not journal.delete(entry_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
