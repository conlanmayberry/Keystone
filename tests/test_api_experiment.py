from __future__ import annotations

import time

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def wait_for_task(client: TestClient, task_id: str, timeout: float = 5.0) -> str:
    """See test_api_strategy.py's wait_for_task docstring: a short grace
    sleep after reaching a terminal status absorbs the narrow window
    between the status commit and the completion event's side effects
    (e.g. strategy metrics) landing.
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


def create_strategy(client: TestClient, workflow_name: str, title: str, template: list[dict]) -> str:
    response = client.post(
        "/strategies",
        json={"workflow_name": workflow_name, "title": title, "plan_template": template, "parameters": ["filename"]},
    )
    return response.json()["id"]


def invoke_n_times(client: TestClient, strategy_id: str, filename_prefix: str, n: int) -> None:
    for i in range(n):
        task_id = client.post(f"/strategies/{strategy_id}/invoke", json={"params": {"filename": f"{filename_prefix}{i}.txt"}}).json()["task_id"]
        wait_for_task(client, task_id)


def test_create_and_list_experiment(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        control = create_strategy(client, "wf", "control", [{"tool_name": "write_file", "args": {"path": "{filename}", "content": "x"}}])
        variant = create_strategy(client, "wf", "variant", [{"tool_name": "write_file", "args": {"path": "{filename}", "content": "y"}}])

        response = client.post(
            "/experiments",
            json={
                "workflow_name": "wf",
                "hypothesis": "variant is better",
                "control_strategy_id": control,
                "variant_strategy_id": variant,
                "minimum_sample_size": 3,
            },
        )
        assert response.status_code == 200
        experiment_id = response.json()["id"]

        listing = client.get("/experiments", params={"workflow_name": "wf"}).json()
        assert len(listing) == 1
        assert listing[0]["id"] == experiment_id
        assert listing[0]["status"] == "running"


def test_evaluate_experiment_promotes_variant_and_creates_promotion_request(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        # Control writes to a path that always succeeds (both are plain
        # writes here — the point is exercising the full route/evaluate/
        # promotion wiring, not reproducing Phase 3's demo-script scenario).
        control = create_strategy(client, "wf2", "control", [{"tool_name": "write_file", "args": {"path": "{filename}", "content": "x"}}])
        variant = create_strategy(client, "wf2", "variant", [{"tool_name": "write_file", "args": {"path": "{filename}", "content": "y"}}])

        invoke_n_times(client, control, "c", 3)
        invoke_n_times(client, variant, "v", 3)

        experiment_id = client.post(
            "/experiments",
            json={
                "workflow_name": "wf2",
                "hypothesis": "h",
                "control_strategy_id": control,
                "variant_strategy_id": variant,
                "minimum_sample_size": 3,
            },
        ).json()["id"]

        result = client.post(f"/experiments/{experiment_id}/evaluate")
        assert result.status_code == 200
        body = result.json()
        assert body["status"] == "concluded"
        # Both strategies always succeed here, so delta is 0 -> keep_control,
        # not promote_variant. Confirm the deterministic, non-random outcome.
        assert body["recommendation"] == "keep_control"

        promotions = client.get("/promotions", params={"status": "pending"}).json()
        assert promotions == []


def test_evaluate_unknown_experiment_returns_404(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post("/experiments/does-not-exist/evaluate")
        assert response.status_code == 404
