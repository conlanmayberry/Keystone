from __future__ import annotations

import time

from fastapi.testclient import TestClient

from megachud.conversation.engine import ConversationEngine
from megachud.llm.client import LLMRequestError, LLMResponse
from megachud.routing.engine import ModelProfile
from tests.fixtures.fake_llm_client import FakeLLMClient


def wait_for_completion(client: TestClient, task_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    detail = client.get(f"/tasks/{task_id}").json()
    while detail["status"] not in ("succeeded", "failed") and time.monotonic() < deadline:
        time.sleep(0.1)
        detail = client.get(f"/tasks/{task_id}").json()
    return detail


def response_with_turn(action: str, message: str, steps: list[dict] | None = None) -> LLMResponse:
    turn_input: dict = {"action": action, "message": message}
    if steps is not None:
        turn_input["steps"] = steps
    return LLMResponse(
        text="", tokens_input=40, tokens_output=20, model="test-model", stop_reason="tool_use",
        raw_tool_calls=[{"name": "conversation_turn", "input": turn_input}],
    )


def configure_engine(app, response=None, error=None) -> FakeLLMClient:
    fake_client = FakeLLMClient(response=response, error=error)
    app.state.conversation_engine = ConversationEngine(fake_client, app.state.tool_registry, "test-model", 1000)
    app.state.model_profiles = [
        ModelProfile("test-model", cost_per_1k_input_tokens=0.001, cost_per_1k_output_tokens=0.002, quality_tier=1, est_latency_ms=100)
    ]
    return fake_client


def create_conversation(client: TestClient) -> str:
    response = client.post("/conversations")
    assert response.status_code == 200
    return response.json()["id"]


def test_conversation_not_found_returns_404(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.get("/conversations/does-not-exist/messages")
        assert response.status_code == 404


def test_list_conversations_count_and_latest_preview(test_settings):
    from datetime import datetime, timedelta, timezone

    from megachud.api.app import create_app
    from megachud.models.conversation import ConversationMessage

    app = create_app(test_settings)
    with TestClient(app) as client:
        conversation_id = create_conversation(client)

        # Insert messages directly (no LLM engine needed) with distinct,
        # increasing timestamps so "latest" is unambiguous.
        base = datetime.now(timezone.utc)
        session = app.state.session_factory()
        try:
            for i, content in enumerate(["first message", "second message", "LATEST message"]):
                session.add(
                    ConversationMessage(
                        conversation_id=conversation_id,
                        role="user",
                        content=content,
                        created_at=base + timedelta(seconds=i),
                    )
                )
            session.commit()
        finally:
            session.close()

        summary = next(c for c in client.get("/conversations").json() if c["id"] == conversation_id)
        assert summary["message_count"] == 3
        # Field is named last_message_preview — it must be the latest, not the first.
        assert summary["last_message_preview"] == "LATEST message"


def test_list_conversations_handles_conversation_with_no_messages(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    with TestClient(app) as client:
        conversation_id = create_conversation(client)
        summary = next(c for c in client.get("/conversations").json() if c["id"] == conversation_id)
        assert summary["message_count"] == 0
        assert summary["last_message_preview"] is None


def test_no_conversation_engine_configured_returns_503(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    assert app.state.conversation_engine is None
    with TestClient(app) as client:
        conversation_id = create_conversation(client)
        response = client.post(f"/conversations/{conversation_id}/messages", json={"content": "hi"})
        assert response.status_code == 503


def test_ask_question_creates_no_task(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    configure_engine(app, response=response_with_turn("ask_question", "Which file should I write to?"))
    with TestClient(app) as client:
        conversation_id = create_conversation(client)
        response = client.post(f"/conversations/{conversation_id}/messages", json={"content": "write something"})

        assert response.status_code == 200
        body = response.json()
        assert body["user_message"]["role"] == "user"
        assert body["assistant_message"]["content"] == "Which file should I write to?"
        assert body["assistant_message"]["linked_task_id"] is None
        assert body["assistant_message"]["plan_status"] is None

        messages = client.get(f"/conversations/{conversation_id}/messages").json()
        assert len(messages) == 2


def test_auto_mode_propose_plan_runs_task_immediately(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    configure_engine(app, response=response_with_turn(
        "propose_plan", "I'll write the file.",
        steps=[{"tool_name": "write_file", "args": {"path": "chat.txt", "content": "hi"}}],
    ))
    with TestClient(app) as client:
        conversation_id = create_conversation(client)
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "write hi to chat.txt", "execution_mode": "auto"},
        )
        assert response.status_code == 200
        body = response.json()
        task_id = body["assistant_message"]["linked_task_id"]
        assert task_id is not None
        assert body["assistant_message"]["plan_status"] is None

        detail = wait_for_completion(client, task_id)
        assert detail["status"] == "succeeded"

        analytics = client.get("/analytics").json()
        assert analytics["cost_data_available"] is True


def test_semi_manual_propose_plan_does_not_create_task_until_approved(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    configure_engine(app, response=response_with_turn(
        "propose_plan", "I'll write the file.",
        steps=[{"tool_name": "write_file", "args": {"path": "chat.txt", "content": "hi"}}],
    ))
    with TestClient(app) as client:
        conversation_id = create_conversation(client)
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "write hi to chat.txt", "execution_mode": "semi_manual"},
        )
        assert response.status_code == 200
        body = response.json()
        message_id = body["assistant_message"]["id"]
        assert body["assistant_message"]["linked_task_id"] is None
        assert body["assistant_message"]["plan_status"] == "pending"

        approve = client.post(f"/conversations/{conversation_id}/messages/{message_id}/approve_plan")
        assert approve.status_code == 200
        task_id = approve.json()["task_id"]
        assert task_id is not None

        detail = wait_for_completion(client, task_id)
        assert detail["status"] == "succeeded"

        messages = client.get(f"/conversations/{conversation_id}/messages").json()
        assistant = next(m for m in messages if m["id"] == message_id)
        assert assistant["plan_status"] == "approved"
        assert assistant["linked_task_id"] == task_id


def test_semi_manual_reject_plan_never_creates_task(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    configure_engine(app, response=response_with_turn(
        "propose_plan", "I'll write the file.",
        steps=[{"tool_name": "write_file", "args": {"path": "chat.txt", "content": "hi"}}],
    ))
    with TestClient(app) as client:
        conversation_id = create_conversation(client)
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "write hi to chat.txt", "execution_mode": "semi_manual"},
        )
        message_id = response.json()["assistant_message"]["id"]

        reject = client.post(f"/conversations/{conversation_id}/messages/{message_id}/reject_plan")
        assert reject.status_code == 200
        assert reject.json()["task_id"] is None

        messages = client.get(f"/conversations/{conversation_id}/messages").json()
        assistant = next(m for m in messages if m["id"] == message_id)
        assert assistant["plan_status"] == "rejected"
        assert assistant["linked_task_id"] is None


def test_stale_pending_plan_blocks_new_message_with_409(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    configure_engine(app, response=response_with_turn(
        "propose_plan", "plan", steps=[{"tool_name": "write_file", "args": {"path": "a.txt", "content": "x"}}],
    ))
    with TestClient(app) as client:
        conversation_id = create_conversation(client)
        client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "write something", "execution_mode": "semi_manual"},
        )
        response = client.post(f"/conversations/{conversation_id}/messages", json={"content": "another message"})
        assert response.status_code == 409


def test_approve_already_resolved_plan_returns_409(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    configure_engine(app, response=response_with_turn(
        "propose_plan", "plan", steps=[{"tool_name": "write_file", "args": {"path": "a.txt", "content": "x"}}],
    ))
    with TestClient(app) as client:
        conversation_id = create_conversation(client)
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "write something", "execution_mode": "semi_manual"},
        )
        message_id = response.json()["assistant_message"]["id"]
        client.post(f"/conversations/{conversation_id}/messages/{message_id}/reject_plan")

        second_attempt = client.post(f"/conversations/{conversation_id}/messages/{message_id}/approve_plan")
        assert second_attempt.status_code == 409


def test_llm_request_error_produces_synthetic_assistant_message_not_http_error(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    configure_engine(app, error=LLMRequestError("connection refused", retryable=True))
    with TestClient(app) as client:
        conversation_id = create_conversation(client)
        response = client.post(f"/conversations/{conversation_id}/messages", json={"content": "hello"})

        # Must be 200, not a bubbled HTTP error — a raised error here would
        # leave a dangling unanswered user turn and break the NEXT call's
        # strict user/assistant alternation against the real Anthropic API.
        assert response.status_code == 200
        body = response.json()
        assert "couldn't respond" in body["assistant_message"]["content"]
        assert body["assistant_message"]["plan_status"] is None
        assert body["assistant_message"]["linked_task_id"] is None

        # And a follow-up message must still work — proves alternation held.
        follow_up = client.post(f"/conversations/{conversation_id}/messages", json={"content": "still there?"})
        assert follow_up.status_code in (200, 503)  # 503 only if engine got reconfigured mid-test; shouldn't happen here


def test_full_manual_mode_propose_plan_gates_a_low_risk_tool(test_settings):
    from megachud.api.app import create_app

    app = create_app(test_settings)
    configure_engine(app, response=response_with_turn(
        "propose_plan", "I'll read the file.",
        steps=[{"tool_name": "read_file", "args": {"path": "a.txt"}}],
    ))
    with TestClient(app) as client:
        (test_settings.workspace_root / "a.txt").write_text("hi", encoding="utf-8")
        conversation_id = create_conversation(client)
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "read a.txt", "execution_mode": "full_manual"},
        )
        assert response.status_code == 200
        task_id = response.json()["assistant_message"]["linked_task_id"]
        assert task_id is not None

        # read_file is RiskLevel.LOW — never gated in auto mode, but
        # full_manual gates every step, so an approval must appear.
        deadline = time.monotonic() + 5.0
        approvals = []
        while time.monotonic() < deadline:
            approvals = client.get("/approvals?status=pending").json()
            if approvals:
                break
            time.sleep(0.1)
        matching = [a for a in approvals if a["task_id"] == task_id]
        assert matching

        # Resolve it — an unresolved approval leaves the orchestrator's
        # background thread blocked for the full approval timeout, which
        # (via ThreadPoolExecutor's atexit thread-joining) hangs the whole
        # test process at exit rather than just this test.
        client.post(f"/approvals/{matching[0]['id']}/decision", json={"approved": True})
        wait_for_completion(client, task_id)
