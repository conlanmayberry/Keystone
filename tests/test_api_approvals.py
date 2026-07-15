from __future__ import annotations

import time

from fastapi.testclient import TestClient

from megachud.api.app import create_app
from tests.fixtures.dummy_tools import DummyIrreversibleTool


def wait_until(predicate, timeout: float = 5.0, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_high_risk_task_shows_in_pending_approvals_and_approve_unblocks_it(test_settings):
    app = create_app(test_settings)
    app.state.tool_registry.register(DummyIrreversibleTool())

    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            json={"title": "needs approval", "prompt": "p", "tool_calls": [{"tool_name": "dummy_irreversible", "args": {}}]},
        )
        task_id = response.json()["id"]

        found = wait_until(lambda: len(client.get("/approvals?status=pending").json()) > 0)
        assert found, "approval request never appeared in pending list"

        pending = client.get("/approvals?status=pending").json()
        matching = [a for a in pending if a["task_id"] == task_id]
        assert len(matching) == 1
        approval = matching[0]
        assert approval["tool_name"] == "dummy_irreversible"
        assert approval["risk_level"] == "high_irreversible"

        decision = client.post(f"/approvals/{approval['id']}/decision", json={"approved": True, "note": "looks fine"})
        assert decision.status_code == 200

        succeeded = wait_until(lambda: client.get(f"/tasks/{task_id}").json()["status"] == "succeeded")
        assert succeeded

        pending_after = [a for a in client.get("/approvals?status=pending").json() if a["task_id"] == task_id]
        assert pending_after == []


def test_denying_high_risk_task_marks_it_failed(test_settings):
    app = create_app(test_settings)
    app.state.tool_registry.register(DummyIrreversibleTool())

    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            json={"title": "will be denied", "prompt": "p", "tool_calls": [{"tool_name": "dummy_irreversible", "args": {}}]},
        )
        task_id = response.json()["id"]

        found = wait_until(lambda: len(client.get("/approvals?status=pending").json()) > 0)
        assert found

        approval = next(a for a in client.get("/approvals?status=pending").json() if a["task_id"] == task_id)
        client.post(f"/approvals/{approval['id']}/decision", json={"approved": False, "note": "no"})

        failed = wait_until(lambda: client.get(f"/tasks/{task_id}").json()["status"] == "failed")
        assert failed


def test_decision_on_unknown_approval_returns_404(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post("/approvals/does-not-exist/decision", json={"approved": True})
        assert response.status_code == 404
