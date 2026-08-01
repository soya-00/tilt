"""The scout — the first thing in Tilt that goes and looks.

Two properties matter more than everything else here and are tested first:
gathering makes no model call, and nothing the scout finds reaches the journal
without a person choosing it. The second one is what makes the feature
defensible at all; if it ever breaks, the app has started writing your journal
for you.
"""

from __future__ import annotations

import httpx
import pytest

from tilt import feeds
from tilt.agents.base import Completion, Pricing
from tilt.agents.ledger import MeteredProvider
from tilt.agents.scout import (
    MAX_PICKS,
    build_prompt,
    gather,
    interests,
    snap_tags,
    triage,
    unseen,
)
from tilt.feeds import Finding, arxiv_query, parse
from tilt.jobs.scout import look
from tilt.journal import Journal
from tilt.models import BriefItem, BriefOrigin, Entry, EntryKind, ReplyKind, utcnow
from tilt.store import files
from tilt.store.brief import BriefStore
from tilt.store.index import Index

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Attention is not a spotlight</title>
    <summary>
      We argue that selective attention is better modelled as a filter.
    </summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>Memory consolidation during sleep</title>
    <summary>A review of hippocampal replay during quiescence, and what it
    consolidates.</summary>
  </entry>
</feed>
"""

FEED = "https://example.com/feed.xml"

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>A blog</title>
  <item>
    <title>On writing things down</title>
    <link>https://example.com/writing</link>
    <description>Why a note you cannot find is not a note.</description>
  </item>
</channel></rss>
"""


class Picking:
    """Chooses whichever candidate it was told to, and counts its calls."""

    name = "picking"
    pricing = Pricing(0.0, 0.0)
    follows_references = True

    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    async def complete(self, prompt: str, *, system: str | None = None, reference=None):
        self.prompts.append(prompt)
        return Completion(text=self.text, model="picking", tokens_in=1, tokens_out=1)


def metered(index: Index, text: str) -> tuple[MeteredProvider, Picking]:
    inner = Picking(text)
    return MeteredProvider(inner, index, ceiling_usd=1.0), inner


def question(journal: Journal, body: str) -> Entry:
    """A card the distiller left behind — what the scout goes looking on behalf of."""
    now = utcnow()
    entry = Entry(
        id=files.new_id(),
        created=now,
        updated=now,
        body=body,
        kind=EntryKind.CARD,
        reply_kind=ReplyKind.QUESTION,
    )
    journal.index.upsert(entry, files.write(entry, journal.entries_root))
    return entry


def tagged(journal: Journal, body: str, tags: list[str]) -> Entry:
    """An ordinary entry, so the journal has a tag vocabulary to snap against."""
    now = utcnow()
    entry = Entry(id=files.new_id(), created=now, updated=now, body=body, tags=tags)
    journal.index.upsert(entry, files.write(entry, journal.entries_root))
    return entry


def read_already(journal: Journal, url: str) -> Entry:
    now = utcnow()
    entry = Entry(
        id=files.new_id(),
        created=now,
        updated=now,
        body="A source that was read.",
        kind=EntryKind.SOURCE,
        source_url=url,
    )
    journal.index.upsert(entry, files.write(entry, journal.entries_root))
    return entry


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Every test host resolves to a public address.

    The address guard does a real lookup before fetching, which is the point of
    it — but these tests answer over a mock transport and their hostnames are
    RFC 2606 names that resolve nowhere. Stubbing the *lookup* keeps the
    *policy* live: `forbidden` still runs, and the tests below that care about
    it stub this differently.
    """
    monkeypatch.setattr(feeds, "resolve", lambda host: ["93.184.216.34"])


def findings(n: int) -> list[Finding]:
    return [
        Finding(f"Paper {i} on attention", f"https://example.com/{i}", "an abstract", "test")
        for i in range(n)
    ]


# --------------------------------------------------------------------- feeds


def test_atom_and_rss_both_parse_with_the_standard_library() -> None:
    """The reason `feedparser` is not a dependency. Told apart by shape rather
    than by a declared content type, because feeds in the wild get theirs wrong."""
    atom = parse(ATOM, source="arxiv")
    assert [f.title for f in atom] == [
        "Attention is not a spotlight",
        "Memory consolidation during sleep",
    ]
    assert atom[0].url == "http://arxiv.org/abs/2401.00001v1"
    assert "selective attention" in atom[0].summary

    [rss] = parse(RSS, source="blog")
    assert rss.url == "https://example.com/writing"
    assert rss.summary.startswith("Why a note")


def test_a_candidate_with_no_description_never_reaches_triage() -> None:
    """A title with decoration is not something to judge.

    Triage exists so that reading is decided on evidence rather than on a
    headline; a candidate with nothing but a title makes it guess, which is the
    thing the two-pass design is there to avoid.
    """
    thin = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>A complete item</title>
    <link>https://example.com/full</link>
    <description>A description long enough to actually judge the thing by.</description>
  </item>
  <item>
    <title>Headline only</title>
    <link>https://example.com/thin</link>
  </item>
  <item>
    <title>Barely anything</title>
    <link>https://example.com/short</link>
    <description>Read more</description>
  </item>
</channel></rss>
"""
    assert [f.url for f in parse(thin, source="blog")] == ["https://example.com/full"]


def test_a_feed_of_pure_headlines_yields_nothing(caplog) -> None:
    """And says so. Silently useless looks exactly like down, and the two want
    different fixes."""
    headlines = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>One</title><link>https://a.example/1</link></item>"
        "<item><title>Two</title><link>https://a.example/2</link></item>"
        "</channel></rss>"
    )

    with caplog.at_level("WARNING"):
        assert parse(headlines, source="headline.example") == []

    assert "none carry a description" in caplog.text


def test_a_malformed_feed_costs_only_itself() -> None:
    """Somebody else's server emitting broken XML is not a reason to stop looking."""
    assert parse("<feed><entry>unclosed", source="broken") == []
    assert parse("<html><body>not a feed at all</body></html>") == []


def test_arxiv_terms_are_or_ed_rather_than_and_ed() -> None:
    """Requiring every term would return nothing for anyone whose interests are
    not one narrow subfield."""
    query = arxiv_query(["attention", "memory"])
    assert "+OR+" in query.replace("%20", "+").replace("%22", '"')
    assert arxiv_query([]) == ""
    assert arxiv_query(["  "]) == ""


# ------------------------------------------------------------------- gather


async def test_gathering_makes_no_model_call(journal: Journal, index: Index) -> None:
    """The whole two-pass design: the free step builds the list, and the step
    that costs money only ever judges one."""
    question(journal, "Does attention behave like a filter?")
    provider, inner = metered(index, '{"picks": []}')

    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=ATOM))
    async with httpx.AsyncClient(transport=transport) as client:
        found = await gather(journal, ["https://example.com/feed.xml"], client=client)

    assert len(found) == 2
    assert inner.prompts == [], "gathering must not call the model"


async def test_one_feed_being_down_does_not_take_the_pass_with_it(
    journal: Journal,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "broken" in str(request.url):
            raise httpx.ConnectError("refused")
        return httpx.Response(200, text=RSS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found = await gather(
            journal, ["https://broken.example/feed", "https://ok.example/feed"], client=client
        )

    assert [f.title for f in found] == ["On writing things down"]


async def test_the_same_paper_from_two_feeds_is_one_candidate(journal: Journal) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=RSS))
    ) as client:
        found = await gather(journal, ["https://a.example/f", "https://b.example/f"], client=client)

    assert len(found) == 1


# ---------------------------------------------------------- where it may go


def test_the_address_policy_refuses_everything_inside() -> None:
    """The policy on its own, without a network to ask.

    169.254.169.254 is the reason this exists — every cloud provider serves
    credentials there — but the private ranges go with it, because a feed
    pointed at a printer on the LAN is no more legitimate.
    """
    for address in (
        "127.0.0.1",
        "::1",
        "169.254.169.254",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "not-an-address",
    ):
        assert feeds.forbidden(address), address

    for address in ("93.184.216.34", "8.8.8.8", "2606:2800:220:1::1"):
        assert not feeds.forbidden(address), address


async def test_a_feed_pointed_at_the_metadata_service_is_refused(
    journal: Journal, monkeypatch
) -> None:
    """The whole reason the guard exists. Fetching happens in this process, so
    an unchecked feed URL is a request forgery with its output summarised into
    the brief."""
    monkeypatch.setattr(feeds, "resolve", lambda host: ["169.254.169.254"])
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        reached.append(str(request.url))
        return httpx.Response(200, text=RSS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found = await gather(journal, ["http://metadata.example/latest"], client=client)

    assert found == []
    assert reached == [], "the request must not be made at all"


async def test_a_public_url_cannot_redirect_somewhere_private(
    journal: Journal, monkeypatch
) -> None:
    """follow_redirects=True would check only the URL you typed. A host that
    answers 302 Location: http://169.254.169.254/ would walk straight past."""
    monkeypatch.setattr(
        feeds,
        "resolve",
        lambda host: ["169.254.169.254"] if host == "inside.example" else ["93.184.216.34"],
    )
    reached: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        reached.append(str(request.url))
        if "outside" in str(request.url):
            return httpx.Response(302, headers={"location": "http://inside.example/creds"})
        return httpx.Response(200, text=RSS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(feeds.UnsafeFeed, match="inside this machine"):
            await feeds.fetch("https://outside.example/feed", client=client)

    assert reached == ["https://outside.example/feed"], "it stopped at the first hop"


async def test_a_redirect_loop_ends(journal: Journal) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://round.example/again"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(feeds.UnsafeFeed, match="redirected more than"):
            await feeds.fetch("https://round.example/feed", client=client)


async def test_a_feed_larger_than_a_feed_is_refused() -> None:
    """A feed is an index of things to read, not a thing to read. Without a cap
    somebody else's server decides how much memory this process uses."""
    huge = "<rss>" + "x" * (feeds.MAX_FEED_BYTES + 1)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=huge))
    ) as client:
        with pytest.raises(feeds.UnsafeFeed, match="which is not a feed"):
            await feeds.fetch("https://big.example/feed", client=client)


async def test_a_non_http_scheme_never_reaches_the_client() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=RSS))
    ) as client:
        with pytest.raises(feeds.UnsafeFeed, match="not a scheme"):
            await feeds.fetch("file:///etc/passwd", client=client)


def test_questions_come_before_folders(journal: Journal) -> None:
    """A subject is a topic; a question is a gap. Folders are the fallback that
    keeps this working on a journal which has ingested nothing yet."""
    questions, subjects = interests(journal)
    assert (questions, subjects) == ([], [])

    question(journal, "What would show that attention is not a filter?")
    questions, _ = interests(journal)
    assert questions == ["What would show that attention is not a filter?"]


# ------------------------------------------------------------------- triage


async def test_triage_is_the_filter(journal: Journal, index: Index) -> None:
    """Six candidates in, one out — and the prompt saw all six. This is the
    promotion bar's argument applied a level earlier."""
    question(journal, "Does attention behave like a filter?")
    provider, inner = metered(index, '{"picks": [{"n": 4, "why": "argues the opposite"}]}')

    chosen = await triage(journal, provider, findings(6))

    assert len(inner.prompts) == 1, "one call for the lot, not one per candidate"
    assert [p.finding.url for p in chosen] == ["https://example.com/4"]
    assert chosen[0].why == "argues the opposite"
    assert "Paper 5 on attention" in inner.prompts[0], "all six were judged"


async def test_triage_will_not_exceed_its_ceiling(journal: Journal, index: Index) -> None:
    """A model that ignores the instruction still cannot fill the brief. Three
    arrivals a day makes this a backlog inside a week."""
    question(journal, "Does attention behave like a filter?")
    picks = ", ".join(f'{{"n": {i}, "why": "w"}}' for i in range(6))
    provider, _ = metered(index, f'{{"picks": [{picks}]}}')

    chosen = await triage(journal, provider, findings(6))

    assert len(chosen) == MAX_PICKS


async def test_a_proposed_tag_lands_on_the_one_you_already_use(
    journal: Journal, index: Index
) -> None:
    """One vocabulary for the journal, not a second one growing beside it.

    Left alone a model coins "Attention" beside the "attention" already in the
    sidebar, and a week of that is a tag list nobody can use to find anything.
    """
    tagged(journal, "Attention discards most of what arrives.", ["attention"])
    question(journal, "Does attention behave like a filter?")
    provider, inner = metered(
        index,
        '{"picks": [{"n": 0, "why": "w", "tags": ["Attentions", "  #Memory  ", "memory"]}]}',
    )

    chosen = await triage(journal, provider, findings(2))

    assert chosen[0].tags == ["attention", "memory"], "snapped, lowercased, deduped"
    assert "attention" in inner.prompts[0], "the model was shown the vocabulary"


async def test_a_genuinely_new_tag_is_kept(journal: Journal, index: Index) -> None:
    """snap() returning nothing is it declining to guess, not a rejection. A
    subject you have not written about yet is exactly what a scout is for."""
    tagged(journal, "Attention discards most of what arrives.", ["attention"])
    question(journal, "Does attention behave like a filter?")
    provider, _ = metered(index, '{"picks": [{"n": 0, "why": "w", "tags": ["hippocampus"]}]}')

    assert (await triage(journal, provider, findings(2)))[0].tags == ["hippocampus"]


async def test_a_pick_with_no_tags_is_still_a_pick(
    journal: Journal, index: Index
) -> None:
    """Tags are how a candidate is recognised, not what makes it valid."""
    question(journal, "Does attention behave like a filter?")
    provider, _ = metered(index, '{"picks": [{"n": 0, "why": "w"}]}')

    chosen = await triage(journal, provider, findings(2))

    assert len(chosen) == 1
    assert chosen[0].tags == []


def test_no_more_than_three_tags_reach_a_row(journal: Journal) -> None:
    """A row in the brief is one line of chips wide."""
    assert snap_tags(["a", "bb", "ccc", "dddd", "eeeee"], []) == ["a", "bb", "ccc"]
    assert snap_tags("not a list", []) == []
    assert snap_tags(["", "  ", "#"], []) == []


async def test_triage_ignores_a_pick_that_points_at_nothing(
    journal: Journal, index: Index
) -> None:
    """An index out of range is a hallucinated candidate, and filing it would
    put a real-looking item in the brief that came from nowhere."""
    question(journal, "Does attention behave like a filter?")
    provider, _ = metered(
        index, '{"picks": [{"n": 99, "why": "w"}, {"n": "two", "why": "w"}]}'
    )

    assert await triage(journal, provider, findings(3)) == []


async def test_nothing_is_proposed_to_an_empty_journal(
    journal: Journal, index: Index
) -> None:
    """With nothing written there is nothing to go looking on behalf of, and
    anything proposed would be proposed at random."""
    provider, inner = metered(index, '{"picks": [{"n": 0, "why": "w"}]}')

    assert await triage(journal, provider, findings(3)) == []
    assert inner.prompts == [], "and it did not pay to find that out"


async def test_offline_triage_needs_a_real_overlap(
    journal: Journal, provider: MeteredProvider
) -> None:
    """Offline this can only notice shared words, which is a far weaker claim
    than "this might answer that" — so the bar is higher than the connector's."""
    question(journal, "Does attention behave like a filter rather than a spotlight?")

    thin = await triage(journal, provider, [Finding("Sleep in fruit flies", "u", "", "t")])
    assert thin == []

    fat = await triage(
        journal,
        provider,
        [Finding("Attention as a filter, not a spotlight", "u", "", "t")],
    )
    assert len(fat) == 1
    assert "matched offline by keyword" in fat[0].why


def test_the_prompt_asks_for_dissent() -> None:
    """Agreement adds nothing the writer does not already have."""
    prompt = build_prompt(["Is attention a filter?"], ["Memory"], findings(2))
    assert "Is attention a filter?" in prompt
    assert "Memory" in prompt
    assert "[0]" in prompt and "[1]" in prompt


# ---------------------------------------------------------------------- job


async def test_nothing_reaches_the_journal_unasked(
    journal: Journal, index: Index, tmp_path
) -> None:
    """The property the whole design rests on.

    The job runs, finds something, and the journal is untouched. Everything it
    chose is a proposal sitting in the brief until a person picks it.
    """
    question(journal, "Does attention behave like a filter?")
    before = len(journal.index.all_entries())
    brief = BriefStore(tmp_path / "brief")
    provider, _ = metered(index, '{"picks": [{"n": 0, "why": "argues the opposite"}]}')

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=ATOM))
    ) as client:
        summary = await look(journal, provider, brief=brief, feeds=[FEED], client=client)

    assert summary.filed == 1
    assert len(journal.index.all_entries()) == before, "the journal must be untouched"
    [item] = brief.all()
    assert item.origin is BriefOrigin.SCOUT
    assert item.why == "argues the opposite"


async def test_a_job_with_nowhere_to_write_says_so(
    journal: Journal, provider: MeteredProvider
) -> None:
    summary = await look(journal, provider, brief=None)
    assert summary.filed == 0
    assert "nothing to write to" in summary.detail


async def test_a_job_that_finds_nothing_is_not_a_failure(
    journal: Journal, provider: MeteredProvider, tmp_path
) -> None:
    """A scout that finds something every day is not being selective."""
    summary = await look(journal, provider, brief=BriefStore(tmp_path / "brief"), feeds=[])

    assert summary.filed == 0
    # Named for its actual cause. "Nothing turned up" is also what a healthy
    # quiet morning looks like, and one sentence covering both is how a job
    # reading the wrong settings directory went unnoticed.
    assert "No feeds configured" in summary.detail


def test_unseen_drops_what_is_known() -> None:
    assert [f.url for f in unseen(findings(3), {"example.com/1"})] == [
        "https://example.com/0",
        "https://example.com/2",
    ]


async def test_never_the_same_thing_twice(
    journal: Journal, index: Index, tmp_path
) -> None:
    """Already read and already dismissed are both known, and neither is stored
    in the form the feed will hand back — a trailing slash or a ``www.`` must
    not be enough to make a paper new again.

    The dedup also happens before triage, so a day where everything is already
    seen is a free one.
    """
    question(journal, "Does attention behave like a filter?")
    brief = BriefStore(tmp_path / "brief")
    read_already(journal, "http://arxiv.org/abs/2401.00001v1/")
    brief.save(
        BriefItem(
            id=files.new_id(),
            title="Already turned down",
            url="https://www.arxiv.org/abs/2401.00002v1",
            origin=BriefOrigin.SCOUT,
            created=utcnow(),
            dismissed=True,
        )
    )
    provider, inner = metered(index, '{"picks": [{"n": 0, "why": "w"}]}')

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=ATOM))
    ) as client:
        summary = await look(journal, provider, brief=brief, feeds=[FEED], client=client)

    assert brief.all() == []
    assert inner.prompts == [], "no triage call for a list with nothing new on it"
    assert "already seen" in summary.detail


# ---------------------------------------------------------------- scheduling


def test_the_scout_is_a_job_like_any_other() -> None:
    from tilt.jobs.runner import JOBS

    assert "scout" in JOBS


# ------------------------------------------------------- where settings live


async def test_the_scheduled_scout_reads_the_feeds_you_configured(client) -> None:
    """The check that was missing when the support directory was split out.

    `scout` builds its own settings store rather than taking one — every job in
    the registry has the same two-parameter shape — and the path it rebuilt was
    the pre-split one, inside the journal folder. Loading a file that is not
    there yields defaults rather than an error, so the job reported "no feeds
    configured" every morning to somebody who had configured feeds, and nothing
    anywhere said otherwise.
    """
    client.patch("/settings", json={"feeds": ["https://example.com/feed.xml"]})

    summary = client.post("/agent/jobs/scout").json()

    assert "No feeds configured" not in summary["detail"]
