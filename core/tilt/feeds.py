"""Reading feeds, with the standard library and nothing else.

Atom and RSS are both small enough that `feedparser` would be a dependency
bought for about forty lines. `xml.etree.ElementTree` handles arXiv's Atom and
ordinary RSS 2.0, and this only needs four fields out of either.

Nothing here calls a model. That is the point of the gather pass: the expensive
step is deciding what is worth reading, and it should be handed a list rather
than asked to build one.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx

log = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"

ARXIV_API = "https://export.arxiv.org/api/query"
"""arXiv's own interface, which returns Atom and asks for no key. Queried by
subject rather than scraped.

HTTPS because this is the one feed every user has without choosing it, and what
it returns goes into a model prompt and then into the brief. Over cleartext,
anyone on the path chooses that content — which is the delivery step for every
prompt-injection concern below."""

TIMEOUT = 15.0

MAX_REDIRECTS = 3
"""Enough for the http-to-https and the trailing-slash hops every real feed
makes, few enough that a redirect loop ends quickly."""

MAX_FEED_BYTES = 2_000_000
"""A feed is an index of things to read, not a thing to read. Past this,
somebody else's server is choosing how much memory this process uses."""

MAX_PER_FEED = 20
"""Enough to be worth triaging, few enough that a chatty feed cannot dominate
the candidate list and crowd out everything else."""

SUMMARY_CHARS = 800
"""Abstract-length. Triage reads titles and summaries, never full text — the
whole saving is in not fetching what you have not decided to read."""

MIN_SUMMARY = 40
"""Below this a candidate is a title with decoration, and triage would be
guessing from the headline — which is the thing the two-pass design exists to
avoid. A feed that carries no descriptions therefore contributes nothing, and
that is the right outcome rather than a bug: the alternative is paying a model
to rank headlines."""


@dataclass(frozen=True)
class Finding:
    """One candidate, before anybody has decided it is worth reading."""

    title: str
    url: str
    summary: str = ""
    source: str = ""
    """Which feed it came from, so the brief can say where it was found."""


class UnsafeFeed(Exception):
    """A feed URL that resolves somewhere this service will not go."""


def forbidden(address: str) -> bool:
    """Whether an address is somewhere this service refuses to go.

    The policy, kept separate from the lookup so it can be tested against a
    list of addresses rather than against the network. ``169.254.169.254`` is
    the reason this exists — every cloud provider serves credentials there —
    but the whole private range goes with it, because a feed pointed at a
    printer on the LAN is no more legitimate.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve(host: str) -> list[str]:
    """Every address a host answers to. Separated from :func:`forbidden` so the
    policy is testable without a network and this is stubbable without one."""
    return [str(sockaddr[0]) for *_head, sockaddr in socket.getaddrinfo(host, None)]


def check_reachable(url: str) -> None:
    """Refuse a URL that points back inside the machine or its network.

    Feed URLs come from the settings route, which is to say from whoever can
    reach the service. Fetching happens *here*, in-process, with whatever
    network position this process has — so an unchecked feed is a request
    forgery whose output gets summarised into the brief.

    The honest limit: this resolves the name and then hands the *name* to httpx,
    which resolves it again. A DNS record that changes between the two answers
    slips through. Closing that means pinning the resolved address through a
    custom transport, which is more machinery than this warrants — recorded
    rather than papered over.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeFeed(f"{parsed.scheme or 'that'} is not a scheme Tilt will fetch.")
    if not parsed.hostname:
        raise UnsafeFeed("That feed URL has no host.")

    try:
        addresses = resolve(parsed.hostname)
    except OSError as exc:
        raise UnsafeFeed(f"Could not resolve {parsed.hostname}.") from exc

    for address in addresses:
        if forbidden(address):
            raise UnsafeFeed(
                f"{parsed.hostname} resolves to {address}, which is inside this "
                "machine or its network. Tilt fetches feeds from the public "
                "internet only."
            )


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> str:
    """One feed, with redirects followed by hand so each hop is checked.

    ``follow_redirects=True`` would check only the URL the user typed, and a
    public host that answers ``302 Location: http://169.254.169.254/`` would
    walk straight past the guard. Following them here means the guard applies
    to where the request actually ends up.
    """
    owned = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            check_reachable(url)
            response = await client.get(
                url,
                headers={"User-Agent": "Tilt/0.3 (journal)"},
                follow_redirects=False,
            )
            if response.is_redirect and response.headers.get("location"):
                url = str(response.next_request.url) if response.next_request else ""
                if not url:
                    raise UnsafeFeed("That feed redirected to nowhere.")
                continue
            response.raise_for_status()
            return _bounded(response, url)
        raise UnsafeFeed(f"That feed redirected more than {MAX_REDIRECTS} times.")
    finally:
        if owned:
            await client.aclose()


def _bounded(response: httpx.Response, url: str) -> str:
    """The body, refused rather than buffered if it is absurd.

    A feed is an index of things to read, not a thing to read. Nothing
    legitimate is larger than this, and the alternative to a cap is letting
    somebody else's server decide how much memory this process uses.
    """
    body = response.content
    if len(body) > MAX_FEED_BYTES:
        raise UnsafeFeed(
            f"{url} returned more than {MAX_FEED_BYTES // 1_000_000}MB, which is "
            "not a feed."
        )
    return body.decode(response.encoding or "utf-8", errors="replace")


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
        return _reported(_atom(root, source), root, f"{ATOM}entry", source)
    if root.tag == "rss" or root.find("channel") is not None:
        return _reported(_rss(root, source), root, ".//item", source)
    log.warning("feed %s is neither Atom nor RSS", source or "?")
    return []


def _reported(
    found: list[Finding], root: ET.Element, tag: str, source: str
) -> list[Finding]:
    """Say when a feed parsed fine and still gave nothing.

    A feed serving only headlines is silently useless otherwise, and it looks
    exactly like a feed that is down — which wants a different fix.
    """
    if not found and root.findall(tag):
        log.warning(
            "feed %s has items but none carry a description; nothing to triage",
            source or "?",
        )
    return found


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
        if _complete(title, url, summary, source):
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
        if _complete(title, url, summary, source):
            out.append(Finding(title, url, summary[:SUMMARY_CHARS], source or "rss"))
    return out


def _complete(title: str, url: str, summary: str, source: str) -> bool:
    """Whether there is enough here to be worth a model's judgement.

    Said out loud rather than dropped quietly. A feed whose items all fail this
    looks identical to a feed that is down, and the two want different fixes.
    """
    if not (title and url):
        return False
    # The one place every finding passes through, so the one place worth
    # checking the scheme. A feed chooses this string, it is stored in the
    # brief, and it ends up in an anchor's href — where `javascript:` or
    # `data:` is a link the interface would otherwise render.
    if not url.lower().startswith(("http://", "https://")):
        log.debug(
            "skipping %r from %s: %r is not a web address",
            title[:60],
            source or "?",
            url[:40],
        )
        return False
    if len(summary) < MIN_SUMMARY:
        log.debug("skipping %r from %s: no description", title[:60], source or "?")
        return False
    return True


def _text(element: ET.Element, tag: str) -> str:
    """Collapsed whitespace, because feed XML is indented and the indentation
    ends up inside the text of every element."""
    found = element.find(tag)
    return " ".join((found.text or "").split()) if found is not None else ""
