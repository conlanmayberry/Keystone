from __future__ import annotations

import time

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def wait_for_completion(client: TestClient, task_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    detail = client.get(f"/tasks/{task_id}").json()
    while detail["status"] not in ("succeeded", "failed") and time.monotonic() < deadline:
        time.sleep(0.1)
        detail = client.get(f"/tasks/{task_id}").json()
    return detail


def test_create_and_get_task_runs_to_completion(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            json={
                "title": "smoke",
                "prompt": "write and read a file",
                "tool_calls": [
                    {"tool_name": "write_file", "args": {"path": "a.txt", "content": "hi"}},
                    {"tool_name": "read_file", "args": {"path": "a.txt"}},
                ],
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]

        detail = wait_for_completion(client, task_id)

        assert detail["status"] == "succeeded"
        assert len(detail["events"]) > 0
        assert detail["evaluation"]["success"] is True


def test_list_tasks_returns_created_task(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        client.post("/tasks", json={"title": "t1", "prompt": "p", "tool_calls": []})
        response = client.get("/tasks")
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "t1" in titles


def test_get_missing_task_returns_404(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.get("/tasks/does-not-exist")
        assert response.status_code == 404


def test_working_summary_reflects_plan(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            json={
                "title": "summary test",
                "prompt": "do the thing",
                "tool_calls": [{"tool_name": "write_file", "args": {"path": "x.txt", "content": "y"}}],
            },
        )
        task_id = response.json()["id"]
        wait_for_completion(client, task_id)

        summary = client.get(f"/tasks/{task_id}/working_summary").json()
        assert summary["objective"] == "do the thing"
        assert len(summary["plan"]) == 1
