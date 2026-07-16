from __future__ import annotations

import time

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def wait_for_task(client: TestClient, task_id: str, timeout: float = 5.0) -> str:
    """See test_api_strategy.py's wait_for_task docstring for the grace-sleep
    rationale."""
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/tasks/{task_id}").json()["status"]
        if status in ("succeeded", "failed"):
            time.sleep(0.2)
            return status
        time.sleep(0.1)
    return status


def run_failing_shell_tasks(client: TestClient, n: int) -> None:
    # test_settings' ShellConfig has an empty allowlist by default, so every
    # shell_exec call fails deterministically regardless of the command —
    # exactly what's needed to trip the tool_failure_rate bottleneck check
    # without depending on any real external command behavior.
    for i in range(n):
        response = client.post(
            "/tasks",
            json={
                "title": f"flaky {i}",
                "prompt": "run a shell command",
                "tool_calls": [{"tool_name": "shell_exec", "args": {"command": "python --version"}}],
            },
        )
        wait_for_task(client, response.json()["id"])


def test_bottleneck_scan_finds_tool_failure_rate(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        run_failing_shell_tasks(client, 6)

        findings = client.get("/bottlenecks").json()
        matching = [f for f in findings if f["kind"] == "tool_failure_rate" and f["subject"] == "shell_exec"]
        assert len(matching) == 1
        assert matching[0]["severity"] == 1.0


def test_bottleneck_scan_empty_on_fresh_db(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        findings = client.get("/bottlenecks").json()
        assert findings == []


def test_propose_experiment_from_non_declining_finding_returns_none(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post(
            "/bottlenecks/propose_experiment",
            json={"kind": "tool_failure_rate", "subject": "shell_exec", "detail": "d", "severity": 1.0},
        )
        assert response.status_code == 200
        assert response.json()["experiment_id"] is None
