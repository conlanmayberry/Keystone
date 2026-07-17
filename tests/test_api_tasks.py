from __future__ import annotations

import time

from fastapi.testclient import TestClient

from megachud.api.app import create_app
from megachud.llm.client import LLMRequestError, LLMResponse
from megachud.orchestrator.llm_planner import LLMTaskPlanner
from megachud.routing.engine import ModelProfile
from tests.fixtures.fake_llm_client import FakeLLMClient


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


def test_created_task_is_tagged_with_current_agent_and_filterable(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        client.post("/tasks", json={"title": "tagged", "prompt": "p", "tool_calls": []})
        agent_id = client.get("/agents").json()[0]["id"]

        matching = client.get(f"/tasks?agent_id={agent_id}").json()
        assert "tagged" in [t["title"] for t in matching]

        non_matching = client.get("/tasks?agent_id=some-other-agent-id").json()
        assert "tagged" not in [t["title"] for t in non_matching]


def test_auto_plan_with_tool_calls_also_set_returns_422(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            json={"title": "t", "prompt": "p", "auto_plan": True, "tool_calls": [{"tool_name": "read_file", "args": {}}]},
        )
        assert response.status_code == 422


def test_auto_plan_with_no_planner_configured_returns_503(test_settings):
    app = create_app(test_settings)
    app.state.llm_task_planner = None
    with TestClient(app) as client:
        response = client.post("/tasks", json={"title": "t", "prompt": "p", "auto_plan": True})
        assert response.status_code == 503


def test_auto_plan_with_planner_raising_llm_request_error_returns_502(test_settings):
    app = create_app(test_settings)
    fake_client = FakeLLMClient(error=LLMRequestError("down", retryable=True))
    app.state.llm_task_planner = LLMTaskPlanner(fake_client, app.state.tool_registry, "test-model", 1000)
    with TestClient(app) as client:
        response = client.post("/tasks", json={"title": "t", "prompt": "p", "auto_plan": True})
        assert response.status_code == 502


def test_auto_plan_happy_path_creates_task_and_runs_through_real_orchestrator(test_settings):
    app = create_app(test_settings)
    fake_client = FakeLLMClient(
        response=LLMResponse(
            text="", tokens_input=40, tokens_output=20, model="test-model", stop_reason="tool_use",
            raw_tool_calls=[{
                "name": "submit_plan",
                "input": {"steps": [{"tool_name": "write_file", "args": {"path": "auto.txt", "content": "hi"}}]},
            }],
        )
    )
    app.state.llm_task_planner = LLMTaskPlanner(fake_client, app.state.tool_registry, "test-model", 1000)
    app.state.model_profiles = [
        ModelProfile("test-model", cost_per_1k_input_tokens=0.001, cost_per_1k_output_tokens=0.002, quality_tier=1, est_latency_ms=100)
    ]

    with TestClient(app) as client:
        response = client.post("/tasks", json={"title": "auto", "prompt": "write a file", "auto_plan": True})
        assert response.status_code == 200
        task_id = response.json()["id"]

        detail = wait_for_completion(client, task_id)
        assert detail["status"] == "succeeded"

        analytics = client.get("/analytics").json()
        assert analytics["cost_data_available"] is True


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
