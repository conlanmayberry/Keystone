from __future__ import annotations

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def test_status_idle(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        body = client.get("/status").json()
        assert body["active"] is False
        assert body["in_flight"] == 0
        assert body["open_tasks"] == 0
        assert body["uptime_seconds"] >= 0
        assert body["working_seconds"] is None


def test_thoughts_empty_then_records(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        assert client.get("/thoughts").json() == []

        app.state.thought_log.record("planner", "Planned 2 steps: write_file, read_file")
        thoughts = client.get("/thoughts").json()
        assert len(thoughts) == 1
        assert thoughts[0]["source"] == "planner"
        assert "Planned 2 steps" in thoughts[0]["text"]
