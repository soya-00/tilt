"""Deciding what a piece of source material is.

A pure function over a filename, a content type, a URL and some text. No IO,
no model call, no guessing at bytes — everything it needs is in the metadata
that arrived with the thing, which makes it exhaustively testable and keeps the
interesting failure modes out of the network path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class Medium(StrEnum):
    """What kind of thing arrived, and therefore how to read it."""

    TEXT = "text"
    """Already words. Pasted prose, .txt, .md — nothing to do."""
    SUBTITLES = "subtitles"
    """.srt or .vtt. Words wrapped in timing that has to come off first."""
    PDF = "pdf"
    """Extractable text. Scans without a text layer are refused, not guessed at."""
    ARTICLE = "article"
    """A web page. Fetched and read by the model, not by a scraper here."""
    VIDEO = "video"
    """A YouTube link. Watched by the model directly — no transcript needed."""
    UNSUPPORTED = "unsupported"
    """Recognised and declined. Audio and video files land here."""


@dataclass(frozen=True)
class Route:
    medium: Medium
    """How to turn this into something the distiller can use."""

    title: str = ""
    """A name for the source, derived from the filename or URL when absent."""

    url: str | None = None
    """Set for the two media the model reads itself."""

    reason: str = ""
    """Why an unsupported thing was declined. Shown to the user verbatim, so it
    says what to do instead rather than only what went wrong."""


_SUBTITLES = (".srt", ".vtt")
_TEXTUAL = (".txt", ".md", ".markdown", ".csv", ".json", ".log", ".rst", ".text")
_AUDIO = (".mp3", ".m4a", ".wav", ".aiff", ".flac", ".ogg", ".aac", ".wma")
_MOVING = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm")

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def _suffix(filename: str) -> str:
    match = re.search(r"(\.[A-Za-z0-9]{1,10})$", filename.strip())
    return match.group(1).lower() if match else ""


def _stem(filename: str) -> str:
    name = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.[A-Za-z0-9]{1,10}$", "", name).strip() or name


def is_youtube(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _YOUTUBE_HOSTS


def _title_from_url(url: str) -> str:
    """A readable name for a link, before anything has been fetched.

    The last meaningful path segment, de-slugged. Better than showing a raw
    URL in the Stream while the model is still reading the page, and it is
    replaced by the real title once the source has been distilled.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return url[:80]
    segments = [s for s in parsed.path.split("/") if s and not re.fullmatch(r"[0-9a-f-]{8,}", s)]
    if not segments:
        return (parsed.hostname or url)[:80]
    slug = re.sub(r"\.[A-Za-z0-9]{1,10}$", "", segments[-1])
    return re.sub(r"[-_]+", " ", slug).strip()[:80] or (parsed.hostname or url)[:80]


def classify(
    *,
    filename: str = "",
    content_type: str = "",
    url: str = "",
    text: str = "",
) -> Route:
    """Work out what arrived.

    A URL wins over a filename: when someone shares a link, the link is the
    source, and whatever the last path segment happens to end in is incidental.
    """
    if url.strip():
        link = url.strip()
        if is_youtube(link):
            return Route(Medium.VIDEO, title=_title_from_url(link), url=link)
        # A link straight to a PDF is still a document, and the model reads
        # those better through url_context than we would by downloading it.
        return Route(Medium.ARTICLE, title=_title_from_url(link), url=link)

    suffix = _suffix(filename)
    kind = (content_type or "").split(";")[0].strip().lower()
    title = _stem(filename)

    if suffix in _SUBTITLES or kind in {"application/x-subrip", "text/vtt"}:
        return Route(Medium.SUBTITLES, title=title)
    if suffix == ".pdf" or kind == "application/pdf":
        return Route(Medium.PDF, title=title)
    if suffix in _AUDIO or kind.startswith("audio/"):
        return Route(
            Medium.UNSUPPORTED,
            title=title,
            reason=(
                "Tilt cannot transcribe audio yet. Paste the transcript instead "
                "and it will be distilled the same way."
            ),
        )
    if suffix in _MOVING or kind.startswith("video/"):
        return Route(
            Medium.UNSUPPORTED,
            title=title,
            reason=(
                "Tilt cannot watch a video file. A YouTube link works, or paste "
                "the transcript."
            ),
        )
    if suffix in _TEXTUAL or kind.startswith("text/") or text.strip():
        return Route(Medium.TEXT, title=title)

    return Route(
        Medium.UNSUPPORTED,
        title=title,
        reason=f"Tilt does not know how to read {suffix or 'that kind of file'} yet.",
    )
