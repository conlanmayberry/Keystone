from __future__ import annotations

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def test_analytics_on_fresh_db(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.get("/analytics")
        assert response.status_code == 200
        payload = response.json()
        assert payload["cost_data_available"] is False
        assert payload["task_counts_by_status"] == {}


def test_analytics_reflects_completed_task(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        create_response = client.post(
            "/tasks",
            json={
                "title": "write a file",
                "prompt": "write hello.txt",
                "tool_calls": [{"tool_name": "write_file", "args": {"path": "hello.txt", "content": "hi"}}],
            },
        )
        task_id = create_response.json()["id"]

        import time

        for _ in range(50):
            if client.get(f"/tasks/{task_id}").json()["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.1)

        response = client.get("/analytics?window_hours=24")
        payload = response.json()
        assert payload["task_counts_by_status"].get("succeeded", 0) >= 1
        assert "write_file" in payload["tool_call_counts"]
