"""Chat interface demo: drives the real /conversations HTTP API (via
FastAPI's TestClient, so this exercises the exact route code the
dashboard's Chat tab calls, in-process — no server needs to be running)
through all three execution modes against a real Anthropic API call:

- Auto: the proposed plan launches immediately.
- Semi-Manual: the plan sits pending until approve_plan is called once,
  then runs to completion.
- Full-Manual: every tool call (not just HIGH_IRREVERSIBLE ones) pauses
  for approval via the existing ApprovalGate — this script approves each
  one as it appears, same as a human clicking "Approve" in the dashboard's
  Pending Approvals panel would.

Requires ANTHROPIC_API_KEY. With no key configured, conversations can
still be created (they don't need an LLM), but sending a message returns
a clean 503 — demonstrated gracefully below, same pattern as
run_llm_demo.py's no-key path.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from megachud.api.app import create_app
from megachud.config import Settings

TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def _wait_for_terminal_status(client: TestClient, task_id: str, *, timeout_seconds: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    task = client.get(f"/tasks/{task_id}").json()
    while task["status"] not in TERMINAL_STATUSES and time.monotonic() < deadline:
        time.sleep(0.3)
        task = client.get(f"/tasks/{task_id}").json()
    return task


def run_auto_mode(client: TestClient) -> None:
    print("\n=== Auto mode ===")
    conversation = client.post("/conversations").json()
    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": 'Write "hello from auto mode" to auto_demo.txt', "execution_mode": "auto"},
    ).json()
    assistant = response["assistant_message"]
    print(f"assistant: {assistant['content']}")
    if assistant["linked_task_id"]:
        task = _wait_for_terminal_status(client, assistant["linked_task_id"])
        print(f"task status: {task['status']}")


def run_semi_manual_mode(client: TestClient) -> None:
    print("\n=== Semi-Manual mode ===")
    conversation = client.post("/conversations").json()
    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": 'Write "hello from semi-manual mode" to semi_demo.txt', "execution_mode": "semi_manual"},
    ).json()
    assistant = response["assistant_message"]
    print(f"assistant: {assistant['content']}")
    print(f"plan_status: {assistant['plan_status']}")
    if assistant["plan_status"] != "pending":
        return

    decision = client.post(f"/conversations/{conversation['id']}/messages/{assistant['id']}/approve_plan").json()
    print(f"approved -> task_id={decision['task_id']}")
    task = _wait_for_terminal_status(client, decision["task_id"])
    print(f"task status: {task['status']}")


def run_full_manual_mode(client: TestClient) -> None:
    print("\n=== Full-Manual mode ===")
    conversation = client.post("/conversations").json()
    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": 'Write "hello from full-manual mode" to full_demo.txt', "execution_mode": "full_manual"},
    ).json()
    assistant = response["assistant_message"]
    print(f"assistant: {assistant['content']}")
    task_id = assistant["linked_task_id"]
    if not task_id:
        print("no task launched (the LLM asked a clarifying question instead of proposing a plan)")
        return

    deadline = time.monotonic() + 15.0
    approved_count = 0
    task = client.get(f"/tasks/{task_id}").json()
    while task["status"] not in TERMINAL_STATUSES and time.monotonic() < deadline:
        pending = [a for a in client.get("/approvals?status=pending").json() if a["task_id"] == task_id]
        if pending:
            client.post(f"/approvals/{pending[0]['id']}/decision", json={"approved": True})
            approved_count += 1
        else:
            time.sleep(0.3)
        task = client.get(f"/tasks/{task_id}").json()
    print(f"task status: {task['status']} (approved {approved_count} step(s) individually)")


def main() -> None:
    settings = Settings.load()
    app = create_app(settings)
    client = TestClient(app)

    if not settings.anthropic_api_key:
        conversation = client.post("/conversations").json()
        response = client.post(
            f"/conversations/{conversation['id']}/messages",
            json={"content": "anything", "execution_mode": "auto"},
        )
        print(
            "No ANTHROPIC_API_KEY found (neither in the environment nor in .env) — "
            "conversations can still be created, but sending a message returns a "
            f"clean {response.status_code}: {response.json()['detail']}"
        )
        return

    run_auto_mode(client)
    run_semi_manual_mode(client)
    run_full_manual_mode(client)


if __name__ == "__main__":
    main()
