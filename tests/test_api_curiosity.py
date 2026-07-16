from __future__ import annotations

import time

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def wait_for_task(client: TestClient, task_id: str, timeout: float = 5.0) -> str:
    """See test_api_strategy.py's wait_for_task docstring: a short grace
    sleep after reaching a terminal status absorbs the narrow window
    between the status commit and the completion event's side effects
    (reflection, memory, and here curiosity) landing.
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


def run_novel_failing_task(client: TestClient) -> str:
    response = client.post(
        "/tasks",
        json={
            "title": "investigate an unfamiliar configuration issue",
            "prompt": "investigate an unfamiliar configuration issue in a totally unprecedented way",
            "tool_calls": [{"tool_name": "write_file", "args": {"path": "broken.py", "content": "not valid python {{{"}}],
        },
    )
    task_id = response.json()["id"]
    status = wait_for_task(client, task_id)
    assert status == "failed"
    return task_id


def test_novel_failing_task_raises_a_pending_question(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        task_id = run_novel_failing_task(client)

        questions = client.get("/questions", params={"status": "pending"}).json()
        assert any(q["source_task_id"] == task_id for q in questions)


def test_novel_failing_task_raises_research_objectives(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        task_id = run_novel_failing_task(client)

        objectives = client.get("/research_objectives").json()
        matching = [o for o in objectives if o["source_task_id"] == task_id]
        assert {o["objective_type"] for o in matching} == {"search_memory", "inspect_previous_work"}


def test_answer_question_creates_retrievable_user_memory(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        task_id = run_novel_failing_task(client)
        question = next(q for q in client.get("/questions", params={"status": "pending"}).json() if q["source_task_id"] == task_id)

        response = client.post(f"/questions/{question['id']}/answer", json={"answer": "Validate syntax before writing."})
        assert response.status_code == 200
        assert response.json()["status"] == "answered"

        # Answered questions no longer show up under the pending filter.
        pending_after = client.get("/questions", params={"status": "pending"}).json()
        assert all(q["id"] != question["id"] for q in pending_after)

        user_memory = client.get("/memory", params={"type": "user"}).json()
        assert any("Validate syntax before writing" in m["content"] for m in user_memory)


def test_answer_unknown_question_returns_404(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post("/questions/does-not-exist/answer", json={"answer": "x"})
        assert response.status_code == 404
