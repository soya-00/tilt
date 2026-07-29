"""Turning bytes into words.

Each extractor either returns readable text or raises. Nothing here returns an
empty string quietly: an ingest that appears to succeed and produces an empty
source is worse than one that says it could not read the file.
"""

from __future__ import annotations

import io
import re

from tilt.ingest.route import Medium, Route


class ExtractionError(Exception):
    """The file was recognised but could not be read.

    Carries a message written for the person who dropped the file, not for a
    log — it says what to do next wherever there is something to do.
    """


# "1", then "00:00:01,000 --> 00:00:04,000", in either the comma form (.srt) or
# the dot form (.vtt), optionally with cue settings trailing the timestamp.
_CUE_NUMBER = re.compile(r"^\d+$")
_TIMECODE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?[.,]\d{1,3}\s*-->\s")
_VTT_HEADER = re.compile(r"^(WEBVTT|NOTE|STYLE|REGION)\b")
# <c.colorE5E5E5>, <00:00:01.000>, <i> — karaoke timing and styling markup.
_INLINE_TAG = re.compile(r"</?[a-zA-Z][^>]*>|<\d{2}:\d{2}:\d{2}[.,]\d{1,3}>")


def strip_cues(raw: str) -> str:
    """Pull the speech out of a subtitle file.

    Roughly half of an .srt is timing, and auto-generated captions repeat each
    line as they scroll. Both are pure cost in a context window and pure noise
    in a distilled idea, so both go before anything is sent.
    """
    lines: list[str] = []
    for line in raw.splitlines():
        text = line.strip()
        if not text or _CUE_NUMBER.match(text) or _TIMECODE.match(text):
            continue
        if _VTT_HEADER.match(text):
            continue
        text = _INLINE_TAG.sub("", text).strip()
        # Rolling captions restate the previous line before adding to it.
        if text and text != (lines[-1] if lines else None):
            lines.append(text)

    out = " ".join(lines)
    return re.sub(r"\s{2,}", " ", out).strip()


def read_pdf(data: bytes) -> str:
    """Extract a PDF's text layer.

    No OCR. A scanned page has no text to find, and returning a page of
    whitespace as though it were a source would produce cards about nothing.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ExtractionError("PDF support is not installed.") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - pypdf raises a wide variety
        raise ExtractionError("That PDF could not be read. It may be damaged.") from exc

    text = "\n\n".join(p for p in pages if p)
    if not text.strip():
        raise ExtractionError(
            "That PDF has no text in it — it is probably a scan. Tilt does not "
            "run OCR, so copy the text in yourself if you have it."
        )
    return text


def extract(route: Route, data: bytes) -> str:
    """Read an uploaded file according to its route.

    Only the media that arrive as bytes. A video or an article is a reference
    the model resolves itself and never reaches this function.
    """
    if route.medium is Medium.UNSUPPORTED:
        raise ExtractionError(route.reason or "Tilt cannot read that kind of file.")
    if route.medium in (Medium.VIDEO, Medium.ARTICLE):
        raise ExtractionError("That source is a link, not a file.")

    if route.medium is Medium.PDF:
        return read_pdf(data)

    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        # Not a guess: these are the two encodings a text file that is not
        # UTF-8 actually turns out to be, and latin-1 always decodes, so it is
        # last and acts as the floor.
        for encoding in ("utf-16", "latin-1"):
            try:
                raw = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:  # pragma: no cover - latin-1 cannot fail
            raise ExtractionError("That file is not text Tilt can read.") from None

    text = strip_cues(raw) if route.medium is Medium.SUBTITLES else raw
    if not text.strip():
        raise ExtractionError("That file is empty.")
    return text
