"""Reading feeds, with the standard library and nothing else.

Atom and RSS are both small enough that `feedparser` would be a dependency
bought for about forty lines. `xml.etree.ElementTree` handles arXiv's Atom and
ordinary RSS 2.0, and this only needs four fields out of either.

Nothing here calls a model. That is the point of the gather pass: the expensive
step is deciding what is worth reading, and it should be handed a list rather
than asked to build one.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"

ARXIV_API = "http://export.arxiv.org/api/query"
"""arXiv's own interface, which returns Atom and asks for no key. Queried by
subject rather than scraped."""

TIMEOUT = 15.0
MAX_PER_FEED = 20
"""Enough to be worth triaging, few enough that a chatty feed cannot dominate
the candidate list and crowd out everything else."""

SUMMARY_CHARS = 800
"""Abstract-length. Triage reads titles and summaries, never full text — the
whole saving is in not fetching what you have not decided to read."""


@dataclass(frozen=True)
class Finding:
    """One candidate, before anybody has decided it is worth reading."""

    title: str
    url: str
    summary: str = ""
    source: str = ""
    """Which feed it came from, so the brief can say where it was found."""


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> str:
    owned = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True)
    try:
        response = await client.get(url, headers={"User-Agent": "Tilt/0.3 (journal)"})
        response.raise_for_status()
        return response.text
    finally:
        if owned:
            await client.aclose()


def arxiv_query(terms: list[str], *, limit: int = MAX_PER_FEED) -> str:
    """A search URL for arXiv's API.

    Terms are OR-ed rather than AND-ed. The caller's terms come from folder
    names and open questions, and requiring all of them would return nothing
    for anyone whose interests are not one narrow subfield.
    """
    clean = [t.strip() for t in terms if t.strip()]
    if not clean:
        return ""
    joined = " OR ".join(f'all:"{t}"' for t in clean[:6])
    return (
        f"{ARXIV_API}?search_query={quote(joined)}"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={limit}"
    )


def parse(xml: str, *, source: str = "") -> list[Finding]:
    """Whatever this feed is, as findings.

    Atom and RSS are told apart by their shape rather than by a declaration,
    because plenty of feeds in the wild get their own content type wrong.
    """
    try:
        root = ET.fromstring(xml.strip())
    except ET.ParseError as exc:
        # One broken feed must not take the pass down with it. Somebody else's
        # server emitting malformed XML is not a reason to stop looking.
        log.warning("could not parse feed %s: %s", source or "?", exc)
        return []

    if root.tag == f"{ATOM}feed":
        return _atom(root, source)
    if root.tag == "rss" or root.find("channel") is not None:
        return _rss(root, source)
    log.warning("feed %s is neither Atom nor RSS", source or "?")
    return []


def _atom(root: ET.Element, source: str) -> list[Finding]:
    out = []
    for entry in root.findall(f"{ATOM}entry")[:MAX_PER_FEED]:
        title = _text(entry, f"{ATOM}title")
        # arXiv puts the canonical URL in <id>; most other Atom feeds use a
        # <link href>. Try both rather than assuming either.
        url = _text(entry, f"{ATOM}id")
        if not url.startswith("http"):
            link = entry.find(f"{ATOM}link")
            url = (link.get("href") or "") if link is not None else ""
        summary = _text(entry, f"{ATOM}summary") or _text(entry, f"{ATOM}content")
        if title and url:
            out.append(
                Finding(title, url, summary[:SUMMARY_CHARS], source or "arxiv")
            )
    return out


def _rss(root: ET.Element, source: str) -> list[Finding]:
    channel = root.find("channel")
    items = (channel if channel is not None else root).findall("item")
    out = []
    for item in items[:MAX_PER_FEED]:
        title = _text(item, "title")
        url = _text(item, "link")
        summary = _text(item, "description")
        if title and url:
            out.append(Finding(title, url, summary[:SUMMARY_CHARS], source or "rss"))
    return out


def _text(element: ET.Element, tag: str) -> str:
    """Collapsed whitespace, because feed XML is indented and the indentation
    ends up inside the text of every element."""
    found = element.find(tag)
    return " ".join((found.text or "").split()) if found is not None else ""
