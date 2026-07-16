from __future__ import annotations

import time

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def wait_for_task(client: TestClient, task_id: str, timeout: float = 5.0) -> str:
    """Polls until the task reaches a terminal status, then a short grace
    sleep: task.status commits before the completion event fires (which
    triggers StrategyMetricsHandler/etc.), so a poll landing in that narrow
    window could observe "succeeded" a moment before dependent side effects
    (e.g. strategy metrics) are committed.
    """
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/tasks/{task_id}").json()["status"]
        if status in ("succeeded", "failed"):
            time.sleep(0.2)
            return status
        time.sleep(0.1)
    return status


def create_strategy(client: TestClient) -> str:
    response = client.post(
        "/strategies",
        json={
            "workflow_name": "greet",
            "title": "Greet",
            "plan_template": [{"tool_name": "write_file", "args": {"path": "{filename}", "content": "hi {name}"}}],
            "parameters": ["filename", "name"],
            "tags": ["demo"],
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_create_list_and_get_strategy(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        strategy_id = create_strategy(client)

        listing = client.get("/strategies", params={"workflow_name": "greet"}).json()
        assert len(listing) == 1
        assert listing[0]["id"] == strategy_id
        assert listing[0]["is_active"] is True

        detail = client.get(f"/strategies/{strategy_id}").json()
        assert detail["title"] == "Greet"
        assert detail["sample_count"] == 0


def test_get_unknown_strategy_returns_404(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.get("/strategies/does-not-exist")
        assert response.status_code == 404


def test_invoke_strategy_runs_task_and_updates_metrics(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        strategy_id = create_strategy(client)

        response = client.post(f"/strategies/{strategy_id}/invoke", json={"params": {"filename": "g.txt", "name": "World"}})
        assert response.status_code == 200
        task_id = response.json()["task_id"]

        status = wait_for_task(client, task_id)
        assert status == "succeeded"

        detail = client.get(f"/strategies/{strategy_id}").json()
        assert detail["sample_count"] == 1
        assert detail["success_count"] == 1


def test_invoke_with_missing_param_returns_422(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        strategy_id = create_strategy(client)

        response = client.post(f"/strategies/{strategy_id}/invoke", json={"params": {}})
        assert response.status_code == 422


def test_patch_inactive_strategy_updates_fields(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        control_id = create_strategy(client)
        # Second strategy for the same workflow_name is inactive by default.
        second = client.post(
            "/strategies",
            json={
                "workflow_name": "greet",
                "title": "Greet v2",
                "plan_template": [{"tool_name": "write_file", "args": {"path": "{filename}", "content": "hi {name}"}}],
                "parameters": ["filename", "name"],
            },
        ).json()
        assert second["is_active"] is False

        response = client.patch(f"/strategies/{second['id']}", json={"title": "Greet v2 edited"})
        assert response.status_code == 200
        assert response.json()["title"] == "Greet v2 edited"


def test_patch_active_strategy_is_rejected(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        strategy_id = create_strategy(client)
        response = client.patch(f"/strategies/{strategy_id}", json={"title": "should not apply"})
        assert response.status_code == 409
