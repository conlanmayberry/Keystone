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


def create_strategy(client: TestClient, workflow_name: str, title: str, template: list[dict], is_first: bool) -> str:
    response = client.post(
        "/strategies",
        json={"workflow_name": workflow_name, "title": title, "plan_template": template, "parameters": ["filename"]},
    )
    body = response.json()
    if not is_first:
        # Non-first strategies for a workflow default to inactive, matching
        # the control being the only active one until promotion.
        assert body["is_active"] is False
    return body["id"]


def build_promotion_scenario(client: TestClient) -> tuple[str, str, str]:
    # Control always writes an invalid-Python .py file -> always fails.
    control = create_strategy(
        client, "wf3", "control",
        # No literal '{'/'}' here — render_plan's substitution calls
        # str.format() on every leaf string in the template, so a literal
        # brace in *content* (not a "{param}" placeholder) would raise
        # ValueError: Single '{' encountered in format string.
        [{"tool_name": "write_file", "args": {"path": "{filename}", "content": "not valid python at all"}}],
        is_first=True,
    )
    # Variant always writes a plain .txt file -> always succeeds.
    variant = create_strategy(
        client, "wf3", "variant",
        [{"tool_name": "write_file", "args": {"path": "{filename}.txt", "content": "fine"}}],
        is_first=False,
    )

    for i in range(3):
        task_id = client.post(f"/strategies/{control}/invoke", json={"params": {"filename": f"c{i}.py"}}).json()["task_id"]
        wait_for_task(client, task_id)
    for i in range(3):
        task_id = client.post(f"/strategies/{variant}/invoke", json={"params": {"filename": f"v{i}"}}).json()["task_id"]
        wait_for_task(client, task_id)

    experiment_id = client.post(
        "/experiments",
        json={
            "workflow_name": "wf3",
            "hypothesis": "variant avoids the syntax failures",
            "control_strategy_id": control,
            "variant_strategy_id": variant,
            "minimum_sample_size": 3,
        },
    ).json()["id"]
    return control, variant, experiment_id


def test_evaluate_promotes_variant_and_lists_pending_promotion(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        control, variant, experiment_id = build_promotion_scenario(client)

        result = client.post(f"/experiments/{experiment_id}/evaluate").json()
        assert result["recommendation"] == "promote_variant"

        pending = client.get("/promotions", params={"status": "pending"}).json()
        assert len(pending) == 1
        assert pending[0]["experiment_id"] == experiment_id
        assert pending[0]["to_strategy_id"] == variant
        assert pending[0]["from_strategy_id"] == control


def test_approve_promotion_flips_active_strategy(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        control, variant, experiment_id = build_promotion_scenario(client)
        client.post(f"/experiments/{experiment_id}/evaluate")
        promotion_id = client.get("/promotions", params={"status": "pending"}).json()[0]["id"]

        response = client.post(f"/promotions/{promotion_id}/decision", json={"approved": True, "note": "ship it"})
        assert response.status_code == 200

        control_after = client.get(f"/strategies/{control}").json()
        variant_after = client.get(f"/strategies/{variant}").json()
        assert control_after["is_active"] is False
        assert variant_after["is_active"] is True


def test_deny_promotion_leaves_strategies_unchanged(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        control, variant, experiment_id = build_promotion_scenario(client)
        client.post(f"/experiments/{experiment_id}/evaluate")
        promotion_id = client.get("/promotions", params={"status": "pending"}).json()[0]["id"]

        client.post(f"/promotions/{promotion_id}/decision", json={"approved": False})

        control_after = client.get(f"/strategies/{control}").json()
        assert control_after["is_active"] is True


def test_decide_unknown_promotion_returns_404(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post("/promotions/does-not-exist/decision", json={"approved": True})
        assert response.status_code == 404
