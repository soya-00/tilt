"""The brief: what is in it, how things get there, and how they leave.

The property under all of these is that the brief is a shelf and not a queue.
Nothing here is completed; an item leaves by becoming journal content or by
being turned down, and one that simply sits there is not a failure state.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tilt.models import BriefItem, BriefOrigin, utcnow
from tilt.store.brief import BriefStore, normalise
from tilt.store.files import new_id


def item(
    store: BriefStore,
    *,
    title: str = "Something",
    url: str | None = "https://example.com/a",
    why: str = "because",
    origin: BriefOrigin = BriefOrigin.SCOUT,
    age: timedelta = timedelta(0),
) -> BriefItem:
    return store.save(
        BriefItem(
            id=new_id(),
            title=title,
            url=url,
            why=why,
            origin=origin,
            created=utcnow() - age,
        )
    )


# --------------------------------------------------------------------- store


def test_an_item_survives_a_restart(tmp_path: Path) -> None:
    """Markdown on disk, like everything else that matters.

    The brief is not in the index and never will be, so a store that only
    remembered within one process would lose it entirely on quit.
    """
    saved = item(BriefStore(tmp_path), title="A paper", why="answers the June question")

    reopened = BriefStore(tmp_path).load(saved.id)
    assert reopened is not None
    assert reopened.title == "A paper"
    assert reopened.why == "answers the June question"
    assert reopened.origin is BriefOrigin.SCOUT


def test_a_note_with_no_link_is_a_legitimate_item(tmp_path: Path) -> None:
    """"Read the second half of that book" has no URL and is still reading."""
    store = BriefStore(tmp_path)
    saved = item(store, title="", url=None, why="the second half of Seeing Like a State")

    [only] = store.all()
    assert only.url is None
    assert only.why.startswith("the second half")
    assert only.id == saved.id


def test_dismissal_hides_an_item_without_forgetting_it(tmp_path: Path) -> None:
    """The tombstone is the whole reason dismissal is not deletion: without it
    the scout offers the same paper again tomorrow."""
    store = BriefStore(tmp_path)
    saved = item(store, url="https://arxiv.org/abs/1234.5678")

    store.dismiss(saved.id)

    assert store.all() == []
    assert [i.id for i in store.all(include_dismissed=True)] == [saved.id]
    assert "arxiv.org/abs/1234.5678" in store.seen()


def test_reading_an_item_leaves_no_tombstone(tmp_path: Path) -> None:
    """The one path that removes rather than tombstones. It is an entry in the
    journal now, and `entries.source_url` remembers it better than a dead file
    here would."""
    store = BriefStore(tmp_path)
    saved = item(store)

    assert store.remove(saved.id) is True
    assert store.load(saved.id) is None
    assert store.all(include_dismissed=True) == []


def test_tags_survive_a_restart(tmp_path: Path) -> None:
    """Tags are how a candidate is recognised at a glance. Losing them on quit
    would leave a list of links again."""
    saved = BriefStore(tmp_path).save(
        BriefItem(
            id=new_id(),
            title="A paper",
            url="https://example.com/p",
            tags=["attention", "memory"],
            created=utcnow(),
        )
    )

    reopened = BriefStore(tmp_path).load(saved.id)
    assert reopened is not None
    assert reopened.tags == ["attention", "memory"]


def test_a_single_tag_written_by_hand_still_reads(tmp_path: Path) -> None:
    """`tags: attention` is what a person types, and YAML gives back a string
    rather than a list. The directory is meant to be editable."""
    (tmp_path / "b1.md").write_text(
        "---\nid: b1\ntitle: A paper\ntags: attention\n---\nbecause\n"
    )

    [item] = BriefStore(tmp_path).all()
    assert item.tags == ["attention"]


def test_the_newest_thing_is_at_the_top(tmp_path: Path) -> None:
    store = BriefStore(tmp_path)
    item(store, title="Old", url="https://example.com/old", age=timedelta(days=3))
    item(store, title="New", url="https://example.com/new")

    assert [i.title for i in store.all()] == ["New", "Old"]


def test_one_unreadable_file_costs_only_itself(tmp_path: Path) -> None:
    """A directory of Markdown is a directory someone may edit by hand."""
    store = BriefStore(tmp_path)
    item(store, title="Fine")
    (tmp_path / "broken.md").write_text("---\nid: [unclosed\n---\nbody\n")

    assert [i.title for i in store.all()] == ["Fine"]


def test_the_same_thing_by_two_routes_is_one_thing() -> None:
    """A feed giving one form and a search giving another is one paper, and
    offering both would make the brief look broken on its second day."""
    assert normalise("https://arxiv.org/abs/2401.1v1/") == normalise(
        "http://www.arxiv.org/abs/2401.1V1"
    )
    assert normalise(None) == ""


# -------------------------------------------------------------------- routes


def test_you_can_put_something_there_yourself(client: TestClient) -> None:
    """What stops this being the machine's list rather than yours."""
    response = client.post(
        "/brief",
        json={"url": "https://example.com/essay", "why": "been meaning to read this"},
    )
    assert response.status_code == 201
    assert response.json()["origin"] == "you"

    listed = client.get("/brief").json()
    assert [i["url"] for i in listed] == ["https://example.com/essay"]


def test_a_manual_item_survives_a_restart(client: TestClient, settings) -> None:
    """The half of the brief that is yours is on disk like the rest of it."""
    client.post("/brief", json={"why": "finish the Ostrom chapter"})

    assert [i.why for i in BriefStore(settings.brief_dir).all()] == [
        "finish the Ostrom chapter"
    ]


def test_adding_the_same_link_twice_shows_you_the_first_one(client: TestClient) -> None:
    """You saved it twice because you forgot. The honest response is to show
    you that you had not, rather than to file a duplicate or refuse."""
    first = client.post("/brief", json={"url": "https://example.com/x", "why": "one"})
    again = client.post("/brief", json={"url": "https://example.com/x/", "why": "two"})

    assert again.json()["id"] == first.json()["id"]
    assert again.json()["why"] == "one"
    assert len(client.get("/brief").json()) == 1


def test_adding_something_back_overrides_a_dismissal(client: TestClient) -> None:
    """A no the scout recorded is not binding on you. Putting it back yourself
    is a later and better-informed decision than the one that dismissed it."""
    added = client.post("/brief", json={"url": "https://example.com/y"}).json()
    client.post(f"/brief/{added['id']}/dismiss")
    assert client.get("/brief").json() == []

    client.post("/brief", json={"url": "https://example.com/y"})

    assert [i["id"] for i in client.get("/brief").json()] == [added["id"]]


def test_a_tag_you_type_lands_on_the_one_you_already_use(client: TestClient) -> None:
    """The composer parses `#tags` out of what you wrote; the snapping happens
    here so the rule holds whoever is calling."""
    client.post("/entries", json={"body": "About attention.", "tags": ["attention"]})

    added = client.post(
        "/brief", json={"url": "https://example.com/p", "tags": ["Attentions", "#memory"]}
    ).json()

    assert added["tags"] == ["attention", "memory"]


def test_a_title_you_type_is_the_title_stored(client: TestClient) -> None:
    """No title is invented from the URL — a magazine slug reads as a title
    someone typed badly. Left blank, the view falls back to the host."""
    titled = client.post(
        "/brief", json={"url": "https://example.com/a", "title": "Seeing Like a State"}
    ).json()
    bare = client.post("/brief", json={"url": "https://example.com/b"}).json()

    assert titled["title"] == "Seeing Like a State"
    assert bare["title"] == ""


def test_an_empty_addition_is_refused(client: TestClient) -> None:
    assert client.post("/brief", json={}).status_code == 422


def test_dismissing_something_that_is_not_there_is_a_404(client: TestClient) -> None:
    assert client.post("/brief/nope/dismiss").status_code == 404


def test_a_note_cannot_be_read_for_you(client: TestClient) -> None:
    """There is no link to open, and pretending otherwise would produce an
    entry that looks like something was read."""
    added = client.post("/brief", json={"why": "the second half of that book"}).json()

    response = client.post(f"/brief/{added['id']}/read")

    assert response.status_code == 422
    assert "note to yourself" in response.json()["detail"]
    assert len(client.get("/brief").json()) == 1


def test_reading_a_link_offline_says_so_and_keeps_the_item(client: TestClient) -> None:
    """Offline there is no page to fetch. Saying so beats storing an empty
    entry that looks read — and the item has to stay, or a missing key would
    quietly eat something you asked for."""
    added = client.post("/brief", json={"url": "https://example.com/essay"}).json()

    response = client.post(f"/brief/{added['id']}/read")

    assert response.status_code == 501
    assert "Gemini key" in response.json()["detail"]
    assert [i["id"] for i in client.get("/brief").json()] == [added["id"]]
