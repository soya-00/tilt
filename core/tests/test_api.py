from __future__ import annotations

from fastapi.testclient import TestClient


def _create(client: TestClient, body: str) -> dict:
    response = client.post("/entries", json={"body": body})
    assert response.status_code == 201, response.text
    return response.json()["entry"]


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"ok": True}


def test_status_reports_offline_mode(client: TestClient) -> None:
    body = client.get("/status").json()
    assert body["offline"] is True
    assert body["provider"] == "echo"
    assert body["entries"] == 0


def test_create_and_list_stream(client: TestClient) -> None:
    _create(client, "Attention is a filter.")
    _create(client, "Memory is reconstructive.")

    stream = client.get("/entries").json()
    assert len(stream) == 2
    assert stream[0]["entry"]["body"] == "Memory is reconstructive."
    assert stream[0]["replies"] == []


def test_empty_entry_is_rejected(client: TestClient) -> None:
    assert client.post("/entries", json={"body": "   "}).status_code == 422


def test_get_update_and_delete_roundtrip(client: TestClient) -> None:
    entry = _create(client, "Original wording.")
    entry_id = entry["id"]

    assert client.get(f"/entries/{entry_id}").json()["entry"]["body"] == "Original wording."

    patched = client.patch(f"/entries/{entry_id}", json={"body": "Revised wording."})
    assert patched.json()["body"] == "Revised wording."

    assert client.delete(f"/entries/{entry_id}").status_code == 204
    assert client.get(f"/entries/{entry_id}").status_code == 404


def test_missing_entry_returns_404(client: TestClient) -> None:
    assert client.get("/entries/nope").status_code == 404
    assert client.patch("/entries/nope", json={"body": "x"}).status_code == 404
    assert client.delete("/entries/nope").status_code == 404


def test_search_endpoint(client: TestClient) -> None:
    _create(client, "Kestrels hunt by hovering in place.")
    _create(client, "Albatrosses glide for hours without flapping.")

    hits = client.get("/entries/search", params={"q": "kestrels"}).json()
    assert len(hits) == 1
    assert "Kestrels" in hits[0]["body"]


def test_reflect_threads_a_reply_and_records_a_run(client: TestClient) -> None:
    entry = _create(client, "Attention behaves like a filter rather than a spotlight.")

    reply = client.post("/agent/reflect", json={"entry_id": entry["id"]})
    assert reply.status_code == 200, reply.text
    assert reply.json()["parent"] == entry["id"]
    assert reply.json()["kind"] == "reply"

    thread = client.get(f"/entries/{entry['id']}").json()
    assert len(thread["replies"]) == 1

    runs = client.get("/agent/runs").json()
    assert runs[0]["job"] == "reflect"
    assert runs[0]["status"] == "ok"


def test_status_entry_count_excludes_machine_replies(client: TestClient) -> None:
    """Someone who wrote three things must not be told they have four."""
    entry = _create(client, "A thought worth reflecting on at some length.")
    client.post("/agent/reflect", json={"entry_id": entry["id"]})

    assert client.get("/status").json()["entries"] == 1


def test_reflect_on_missing_entry_returns_404(client: TestClient) -> None:
    assert client.post("/agent/reflect", json={"entry_id": "nope"}).status_code == 404


def test_index_rebuild_endpoint(client: TestClient) -> None:
    _create(client, "One.")
    _create(client, "Two.")
    assert client.post("/index/rebuild").json() == {"indexed": 2}


def test_delete_theme_endpoint_keeps_the_entries(client: TestClient) -> None:
    entry = _create(client, "Attention is a filter that discards most input.")
    client.post("/agent/process", json={"entry_id": entry["id"]})

    themes = client.get("/themes").json()
    assert themes, "the agent should have filed this somewhere"

    assert client.delete(f"/themes/{themes[0]['id']}").status_code == 204
    assert client.get("/themes").json() == []
    # The folder is gone. What was written is not.
    assert client.get(f"/entries/{entry['id']}").status_code == 200
    assert client.get("/status").json()["entries"] == 1


def test_delete_missing_theme_returns_404(client: TestClient) -> None:
    assert client.delete("/themes/nope").status_code == 404


def test_status_names_what_is_asleep_without_a_key(client: TestClient) -> None:
    """Without a key the app still writes, files, connects and draws, so nothing
    looks broken — and what is missing is exactly what nobody would think to go
    looking for. Settings shows this list beside the key field."""
    body = client.get("/status").json()
    assert body["offline"] is True
    assert body["dormant"], "an offline service must say what it cannot do"
    assert any("share no words" in d["capability"] for d in body["dormant"])
    assert all(d["why"].strip() for d in body["dormant"]), "each needs a reason"


def test_status_says_nothing_is_asleep_once_a_key_is_present(
    client: TestClient, settings
) -> None:
    # `offline` is derived from which provider is actually wired up, not from
    # whether a key happens to be in settings — so this fakes the provider.
    settings.gemini_api_key = "test-key"
    client.app.state.provider._provider.name = "gemini"
    assert client.get("/status").json()["dormant"] == []
