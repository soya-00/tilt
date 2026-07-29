"""Working out what arrived, and reading it.

Routing is a pure function over metadata, so it is worth testing exhaustively:
every wrong answer here becomes either a refused file the user could have used
or a garbled source that quietly poisons a set of cards.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from tilt.ingest import ExtractionError, Medium, classify, extract
from tilt.ingest.extract import strip_cues
from tilt.ingest.route import Route

# ------------------------------------------------------------------ routing


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("notes.txt", Medium.TEXT),
        ("README.md", Medium.TEXT),
        ("talk.srt", Medium.SUBTITLES),
        ("talk.vtt", Medium.SUBTITLES),
        ("paper.pdf", Medium.PDF),
        ("lecture.mp3", Medium.UNSUPPORTED),
        ("lecture.mp4", Medium.UNSUPPORTED),
        ("archive.zip", Medium.UNSUPPORTED),
    ],
)
def test_a_file_is_routed_by_its_extension(filename: str, expected: Medium) -> None:
    assert classify(filename=filename).medium is expected


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("application/pdf", Medium.PDF),
        ("text/vtt", Medium.SUBTITLES),
        ("text/plain; charset=utf-8", Medium.TEXT),
        ("audio/mpeg", Medium.UNSUPPORTED),
        ("video/quicktime", Medium.UNSUPPORTED),
    ],
)
def test_a_file_with_no_extension_is_routed_by_its_type(
    content_type: str, expected: Medium
) -> None:
    assert classify(filename="download", content_type=content_type).medium is expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=abc123",
    ],
)
def test_a_youtube_link_is_something_to_watch(url: str) -> None:
    assert classify(url=url).medium is Medium.VIDEO


def test_any_other_link_is_something_to_read() -> None:
    assert classify(url="https://example.com/essays/attention").medium is Medium.ARTICLE


def test_a_link_wins_over_whatever_the_filename_says() -> None:
    """Sharing a link means the link is the source. What its last path segment
    happens to end in is incidental."""
    route = classify(url="https://example.com/paper.pdf", filename="something.txt")
    assert route.medium is Medium.ARTICLE
    assert route.url == "https://example.com/paper.pdf"


def test_a_link_gets_a_readable_name_before_anything_is_fetched() -> None:
    # Better than showing a raw URL in the Stream while the model reads it.
    assert classify(url="https://example.com/essays/on-attention").title == "on attention"


def test_a_declined_file_says_what_to_do_instead() -> None:
    """A refusal that only says "no" leaves the user with a file and no idea
    what to do with it."""
    assert "transcript" in classify(filename="talk.mp3").reason.lower()
    assert "youtube" in classify(filename="talk.mov").reason.lower()


def test_pasted_text_with_no_filename_at_all_is_still_text() -> None:
    assert classify(text="Attention is a filter.").medium is Medium.TEXT


# --------------------------------------------------------------- subtitles


SRT = """1
00:00:01,000 --> 00:00:04,000
Attention is a filter.

2
00:00:04,000 --> 00:00:07,500
It discards most of what arrives.
"""


def test_subtitle_timing_comes_off() -> None:
    """Roughly half an .srt is timecodes. They are pure cost in a context
    window and pure noise in an extracted idea."""
    assert strip_cues(SRT) == "Attention is a filter. It discards most of what arrives."


def test_vtt_headers_and_inline_markup_come_off_too() -> None:
    vtt = (
        "WEBVTT\n\nNOTE generated\n\n"
        "00:00:01.000 --> 00:00:04.000 align:start position:0%\n"
        "<c.colorE5E5E5>Attention</c> is a <i>filter</i>.\n"
    )
    assert strip_cues(vtt) == "Attention is a filter."


def test_rolling_captions_are_not_repeated() -> None:
    """Auto-generated captions restate the previous line as they scroll."""
    rolling = (
        "1\n00:00:01,000 --> 00:00:02,000\nAttention is a filter.\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nAttention is a filter.\n\n"
        "3\n00:00:03,000 --> 00:00:04,000\nIt discards most input.\n"
    )
    assert strip_cues(rolling) == "Attention is a filter. It discards most input."


# ---------------------------------------------------------------- extract


def _pdf(text: str = "") -> bytes:
    """A real PDF, built rather than checked in as a fixture.

    ``text`` empty gives a page with no text layer — which is what a scan looks
    like to an extractor, and the case worth being sure about.
    """
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    page = writer.pages[0]
    if text:
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)

        # A content stream with no font resource extracts as nothing, which
        # would make this fixture indistinguishable from the scan below.
        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        fonts = DictionaryObject()
        fonts[NameObject("/F1")] = writer._add_object(font)
        resources = DictionaryObject()
        resources[NameObject("/Font")] = fonts
        page[NameObject("/Resources")] = resources

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_reading_a_text_file() -> None:
    route = Route(Medium.TEXT)
    assert extract(route, b"Attention is a filter.") == "Attention is a filter."


def test_a_text_file_that_is_not_utf8_still_reads() -> None:
    """Exported transcripts are UTF-16 more often than anyone expects, and
    losing a source to an encoding is not an acceptable outcome."""
    assert "filter" in extract(Route(Medium.TEXT), "Attention is a filter.".encode("utf-16"))


def test_an_empty_file_is_refused_rather_than_ingested() -> None:
    """An ingest that appears to work and produces nothing is worse than one
    that says it could not read the file."""
    with pytest.raises(ExtractionError):
        extract(Route(Medium.TEXT), b"   \n  ")


def test_reading_a_pdf_with_a_text_layer() -> None:
    assert "Attention is a filter" in extract(Route(Medium.PDF), _pdf("Attention is a filter"))


def test_a_scanned_pdf_says_so_rather_than_producing_nothing() -> None:
    """No text layer means no OCR and no guessing — cards about nothing are
    worse than an honest refusal."""
    with pytest.raises(ExtractionError, match="scan"):
        extract(Route(Medium.PDF), _pdf(""))


def test_a_damaged_pdf_does_not_take_the_request_down() -> None:
    with pytest.raises(ExtractionError):
        extract(Route(Medium.PDF), b"not a pdf at all")


def test_a_link_is_not_a_file() -> None:
    with pytest.raises(ExtractionError):
        extract(Route(Medium.ARTICLE, url="https://example.com"), b"")


# ------------------------------------------------------------------- API


def test_uploading_a_subtitle_file_produces_one_source(client: TestClient) -> None:
    body = "".join(
        f"{i}\n00:00:{i:02d},000 --> 00:00:{i + 1:02d},000\n"
        f"Attention is a filter that discards most of what arrives.\n\n"
        for i in range(1, 12)
    )
    response = client.post(
        "/ingest/file",
        files={"file": ("talk.srt", body.encode(), "application/x-subrip")},
    )

    assert response.status_code == 200, response.text
    thread = response.json()
    assert thread["entry"]["kind"] == "source"
    # The name came off the filename; nobody was asked to type one.
    assert thread["entry"]["body"].startswith("talk")


def test_uploading_something_unreadable_is_declined_with_a_reason(
    client: TestClient,
) -> None:
    response = client.post(
        "/ingest/file",
        files={"file": ("lecture.mp3", b"\x00\x01\x02", "audio/mpeg")},
    )

    assert response.status_code == 415
    assert "transcript" in response.json()["detail"].lower()


def test_a_link_with_no_text_needs_a_model_that_can_open_it(client: TestClient) -> None:
    """Offline there is no page to read. Storing an empty source would imply
    something had been."""
    response = client.post("/ingest", json={"url": "https://example.com/essay"})

    assert response.status_code == 501
    assert "key" in response.json()["detail"].lower()


def test_an_empty_post_is_still_a_422(client: TestClient) -> None:
    assert client.post("/ingest", json={"text": "   "}).status_code == 422
