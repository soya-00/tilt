"""Themes, tags, and links — what the sidebar navigates."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from tilt.api.deps import get_journal
from tilt.journal import Journal
from tilt.models import TagCount, Theme

router = APIRouter(tags=["library"])


class RenameTheme(BaseModel):
    label: str = Field(min_length=1, max_length=40)


@router.get("/themes", response_model=list[Theme])
def list_themes(journal: Journal = Depends(get_journal)) -> list[Theme]:
    """Agent-discovered categories, busiest first."""
    return journal.index.themes()


@router.patch("/themes/{theme_id}", response_model=Theme)
def rename_theme(
    theme_id: str, payload: RenameTheme, journal: Journal = Depends(get_journal)
) -> Theme:
    """Rename a theme. This pins the label so the agent stops rewriting it."""
    theme = journal.index.rename_theme(theme_id, payload.label.strip())
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
    again and the dismissal remains available as quality signal.
    """
    if not journal.index.dismiss_link(link_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
