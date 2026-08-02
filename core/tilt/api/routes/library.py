"""Themes, tags, and links — what the sidebar navigates."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from tilt.api.deps import get_journal
from tilt.folders import Declined
from tilt.jobs.misfiled import apply_move, opening
from tilt.jobs.split import apply_split
from tilt.journal import Journal
from tilt.models import Misfiled, TagCount, Theme, ThemeSplit, Thread

router = APIRouter(tags=["library"])


class RenameTheme(BaseModel):
    label: str = Field(min_length=1, max_length=40)


class RefusedMove(BaseModel):
    """A refiling you turned down, with enough of the entry to recognise it.

    `folders.md` stores an entry id and a destination, which is what the keeper
    needs and nothing a person can read. The opening line is joined on here
    rather than written into the file, because it is a copy of something you
    wrote and would go stale the moment you edited the entry.
    """

    entry: str
    to: str
    opening: str


class Rulings(BaseModel):
    """Every decision you have made about your folders, ready to be read back.

    Shaped like `Decisions` in `folders.md` except for the openings above. The
    store keeps what survives a rebuild; this is what a person can act on.
    """

    pinned: list[str] = Field(default_factory=list)
    declined: list[Declined] = Field(default_factory=list)
    refused: list[RefusedMove] = Field(default_factory=list)


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
    split = journal.index.get_split(split_id)
    if split is None or not journal.index.dismiss_split(split_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found.")
    # Written to `folders.md` as well as the index. The index is the store the
    # app promises is safe to delete, and a refusal that only lived there came
    # back as a fresh proposal the first time anybody took it at its word.
    theme = journal.index.get_theme(split.theme_id)
    if theme is not None:
        journal.folders.decline(theme.label, members=theme.count)


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


@router.get("/moves", response_model=list[Misfiled])
def list_moves(journal: Journal = Depends(get_journal)) -> list[Misfiled]:
    """Entries the filing pass thinks are in the wrong folder.

    Usually empty. Filing is right most of the time; this exists for the entries
    written before the better folder existed.
    """
    return journal.index.pending_moves()


@router.post("/moves/{move_id}", response_model=Thread)
def accept_move(move_id: str, journal: Journal = Depends(get_journal)) -> Thread:
    """Refile the entry. Returns its thread, because that is what the row that
    offered this is sitting inside."""
    move = journal.index.get_move(move_id)
    if move is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suggestion not found.")
    if not apply_move(journal, move):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That entry is gone.")
    return journal.thread(move.entry_id)


@router.delete("/moves/{move_id}", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_move(move_id: str, journal: Journal = Depends(get_journal)) -> None:
    """Leave the entry where it is.

    Written to `folders.md` as well as the index, and keyed on the destination:
    "not that folder" is a narrower answer than "never mention this entry
    again", and the narrower one is what was actually said.
    """
    move = journal.index.get_move(move_id)
    if move is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suggestion not found.")
    journal.folders.refuse_move(move.entry_id, move.to_label)
    journal.index.clear_move(move.entry_id)


@router.get("/folders", response_model=Rulings)
def folder_decisions(journal: Journal = Depends(get_journal)) -> Rulings:
    """What you have told the keeper about your folders.

    A name you pinned by renaming, a split you turned down, and an entry you
    told it to leave where it is. All three are kept in `folders.md` beside your
    entries, and all three were invisible — you could accumulate them for months
    with no way to see what you had said or to take any of it back.

    A refusal whose entry is gone is left out rather than shown as an id nobody
    can place. Deleting an entry drops its refusals, so this is the case where
    the file was edited by hand or the entry's Markdown was removed from under
    the app — real, rare, and not worth a row that cannot be acted on.
    """
    decisions = journal.folders.load()
    refused = []
    for item in decisions.refused:
        entry = journal.index.get(item.entry)
        if entry is not None:
            refused.append(
                RefusedMove(entry=item.entry, to=item.to, opening=opening(entry))
            )
    return Rulings(pinned=decisions.pinned, declined=decisions.declined, refused=refused)


@router.delete("/folders/pinned/{label}", status_code=status.HTTP_204_NO_CONTENT)
def unpin(label: str, journal: Journal = Depends(get_journal)) -> None:
    """Let the agent rename this folder again. The name it has now stays until
    the agent has a better one; nothing is renamed by this."""
    decisions = journal.folders.load()
    decisions.pinned = [p for p in decisions.pinned if p.casefold() != label.casefold()]
    journal.folders.save(decisions)


@router.delete("/folders/declined/{label}", status_code=status.HTTP_204_NO_CONTENT)
def ask_again(label: str, journal: Journal = Depends(get_journal)) -> None:
    """Drop a refusal, so the keeper may propose splitting this folder again
    without waiting for it to grow by half."""
    journal.folders.accepted(label)
    # The index carries its own copy of the refusal, and it is the one the
    # nightly pass actually reads.
    theme = next(
        (t for t in journal.index.themes() if t.label.casefold() == label.casefold()), None
    )
    if theme is not None:
        journal.index.clear_split(theme.id)


@router.delete("/folders/refused/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def reconsider_move(
    entry_id: str, to: str, journal: Journal = Depends(get_journal)
) -> None:
    """Drop a refusal, so the keeper may suggest that move again.

    Nothing moves. A refusal is only the reason a suggestion stops being made,
    and taking it back restores the question rather than answering it.

    The destination is a query parameter where the other two routes here take a
    path segment, because this one is keyed on a pair: an entry and the folder
    it declined to go to. Reaching that with a second path segment would put a
    label somebody typed where a `/` changes the route.
    """
    journal.folders.allow_move(entry_id, to)


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
