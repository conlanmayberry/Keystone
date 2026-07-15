from __future__ import annotations

import time

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def test_create_user_memory_and_list(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post("/memory/user", json={"title": "prefs", "content": "I like tabs", "tags": ["style"]})
        assert response.status_code == 200
        body = response.json()
        assert body["memory_type"] == "user"
        assert body["vault_path"] is not None

        listing = client.get("/memory", params={"type": "user"}).json()
        assert len(listing) == 1
        assert listing[0]["title"] == "prefs"


def test_search_memory_returns_ranked_results(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        client.post("/memory/user", json={"title": "fox fact", "content": "the quick brown fox jumps", "tags": []})
        client.post(
            "/memory/user", json={"title": "unrelated", "content": "grocery list of apples and bread", "tags": []}
        )

        response = client.get("/memory/search", params={"q": "a fox jumping quickly", "top_k": 2})
        assert response.status_code == 200
        results = response.json()
        assert results[0]["entry"]["title"] == "fox fact"


def test_reindex_endpoint_runs_on_empty_vault(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post("/memory/reindex")
        assert response.status_code == 200
        body = response.json()
        assert body["created"] == 0
        assert body["errors"] == []


def test_task_completion_creates_retrievable_memory(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            json={
                "title": "make a shopping list",
                "prompt": "write a shopping list to a file",
                "tool_calls": [{"tool_name": "write_file", "args": {"path": "list.txt", "content": "milk, eggs"}}],
            },
        )
        task_id = response.json()["id"]

        deadline = time.monotonic() + 5
        status = None
        while time.monotonic() < deadline:
            status = client.get(f"/tasks/{task_id}").json()["status"]
            if status in ("succeeded", "failed"):
                break
            time.sleep(0.1)
        assert status == "succeeded"

        results = client.get("/memory/search", params={"q": "shopping list", "type": "episodic"}).json()
        assert any(r["entry"]["source_task_id"] == task_id for r in results)


def test_memory_type_filter_excludes_other_types(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        client.post("/memory/user", json={"title": "u", "content": "user content", "tags": []})

        episodic_only = client.get("/memory", params={"type": "episodic"}).json()
        assert episodic_only == []
