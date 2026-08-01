"""Themes, tags, and links — what the sidebar navigates."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from tilt.api.deps import get_journal
from tilt.jobs.split import apply_split
from tilt.journal import Journal
from tilt.models import TagCount, Theme, ThemeSplit

router = APIRouter(tags=["library"])


class RenameTheme(BaseModel):
    label: str = Field(min_length=1, max_length=40)


@router.get("/themes", response_model=list[Theme])
def list_themes(journal: Journal = Depends(get_journal)) -> list[Theme]:
    """Agent-discovered categories, busiest first."""
    return journal.index.themes()


@router.get("/themes/splits", response_model=list[ThemeSplit])
def list_splits(journal: Journal = Depends(get_journal)) -> list[ThemeSplit]:
    """Folders the keeper thinks have become two subjects.

    Declared above the `{theme_id}` routes so "splits" is never read as an id.
    Almost always empty: the pass proposes at most one a night and only when a
    folder measures as divided and the model agrees it is.
    """
    return journal.index.pending_splits()


@router.post("/themes/splits/{split_id}", response_model=list[Theme])
def accept_split(split_id: str, journal: Journal = Depends(get_journal)) -> list[Theme]:
    """Carry out a split. The only thing in the app that does.

    Returns the folder list rather than the two folders, because a split
    rearranges the sidebar and the caller needs the whole of it anyway.
    """
    split = journal.index.get_split(split_id)
    if split is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found.")
    apply_split(journal, split)
    return journal.index.themes()


@router.delete("/themes/splits/{split_id}", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_split(split_id: str, journal: Journal = Depends(get_journal)) -> None:
    """Turn a split down.

    Kept as a tombstone with the folder's size at the time, exactly like a
    dismissed connection: without it the same folder is proposed again tomorrow
    night, and a suggestion that ignores your answer is worse than one you never
    saw. It comes back only once the folder has grown by half again.
    """
    if not journal.index.dismiss_split(split_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found.")


@router.patch("/themes/{theme_id}", response_model=Theme)
def rename_theme(
    theme_id: str, payload: RenameTheme, journal: Journal = Depends(get_journal)
) -> Theme:
    """Rename a theme. This pins the label so the agent stops rewriting it.

    Goes through the journal rather than the index: the new name has to reach
    every member's frontmatter, or the old one comes back on the next boot.
    """
    theme = journal.rename_theme(theme_id, payload.label.strip())
    if theme is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Theme not found.")
    return theme


@router.delete("/themes/{theme_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_theme(theme_id: str, journal: Journal = Depends(get_journal)) -> None:
    """Delete a folder. The entries filed under it are kept.

    Categorisation is the agent's, and this is how the user disagrees with it.
    Nothing anyone wrote is removed — only the folder and the memberships that
    pointed at it, in the index and in each entry's frontmatter.
    """
    if not journal.delete_theme(theme_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Theme not found.")


@router.get("/tags", response_model=list[TagCount])
def list_tags(journal: Journal = Depends(get_journal)) -> list[TagCount]:
    return journal.index.tags()


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_link(link_id: str, journal: Journal = Depends(get_journal)) -> None:
    """Dismiss a connection.

    Kept as a tombstone rather than deleted, so the pair is never proposed
    again and the dismissal remains available as quality signal. Written to
    both entries' frontmatter as well as the index, because the index is
    disposable and the promise is not.
    """
    if not journal.dismiss_link(link_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
