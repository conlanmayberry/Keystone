from __future__ import annotations

import pytest

from megachud.conversation.engine import ConversationEngine
from megachud.llm.client import LLMRequestError, LLMResponse
from megachud.orchestrator.plan_validation import PlanValidationError
from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry
from tests.fixtures.fake_llm_client import FakeLLMClient


def make_registry(tmp_workspace) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool(tmp_workspace))
    registry.register(WriteFileTool(tmp_workspace))
    return registry


def response_with_turn(action: str, message: str, steps: list[dict] | None = None) -> LLMResponse:
    turn_input: dict = {"action": action, "message": message}
    if steps is not None:
        turn_input["steps"] = steps
    return LLMResponse(
        text="", tokens_input=40, tokens_output=20, model="test-model", stop_reason="tool_use",
        raw_tool_calls=[{"name": "conversation_turn", "input": turn_input}],
    )


def test_ask_question_returns_no_plan(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=response_with_turn("ask_question", "Which file should I write to?"))
    engine = ConversationEngine(client, registry, "test-model", 1000)

    result = engine.respond([], "write something")

    assert result.action == "ask_question"
    assert result.message == "Which file should I write to?"
    assert result.plan is None
    assert result.tokens_input == 40
    assert result.tokens_output == 20
    assert result.model == "test-model"


def test_propose_plan_returns_validated_plan(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=response_with_turn(
        "propose_plan", "I'll write and read the file.",
        steps=[
            {"tool_name": "write_file", "args": {"path": "a.txt", "content": "hi"}},
            {"tool_name": "read_file", "args": {"path": "a.txt"}},
        ],
    ))
    engine = ConversationEngine(client, registry, "test-model", 1000)

    result = engine.respond([], "write and read a.txt with 'hi'")

    assert result.action == "propose_plan"
    assert result.message == "I'll write and read the file."
    assert len(result.plan) == 2
    assert result.plan[0].tool_name == "write_file"
    assert result.plan[0].args == {"path": "a.txt", "content": "hi"}


def test_history_is_passed_through_as_plain_messages(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=response_with_turn("ask_question", "And the content?"))
    engine = ConversationEngine(client, registry, "test-model", 1000)
    history = [
        {"role": "user", "content": "write a file"},
        {"role": "assistant", "content": "Which path?"},
    ]

    engine.respond(history, "a.txt")

    sent_messages = client.calls[0]["messages"]
    assert sent_messages == [
        {"role": "user", "content": "write a file"},
        {"role": "assistant", "content": "Which path?"},
        {"role": "user", "content": "a.txt"},
    ]


def test_hallucinated_tool_name_raises_plan_validation_error(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=response_with_turn("propose_plan", "done", steps=[{"tool_name": "delete_universe", "args": {}}]))
    engine = ConversationEngine(client, registry, "test-model", 1000)

    with pytest.raises(PlanValidationError, match="unknown tool"):
        engine.respond([], "do something impossible")


def test_malformed_args_raises_plan_validation_error(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=response_with_turn("propose_plan", "done", steps=[{"tool_name": "write_file", "args": {"path": "a.txt"}}]))
    engine = ConversationEngine(client, registry, "test-model", 1000)

    with pytest.raises(PlanValidationError, match="invalid args"):
        engine.respond([], "write a file")


def test_empty_steps_raises_plan_validation_error(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=response_with_turn("propose_plan", "done", steps=[]))
    engine = ConversationEngine(client, registry, "test-model", 1000)

    with pytest.raises(PlanValidationError, match="empty plan"):
        engine.respond([], "do nothing")


def test_no_tool_use_in_response_raises_plan_validation_error(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=LLMResponse(text="huh", tokens_input=5, tokens_output=5, model="test-model", stop_reason="end_turn"))
    engine = ConversationEngine(client, registry, "test-model", 1000)

    with pytest.raises(PlanValidationError, match="did not return a conversation_turn"):
        engine.respond([], "do something")


def test_unknown_action_raises_plan_validation_error(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=response_with_turn("do_a_backflip", "wat"))
    engine = ConversationEngine(client, registry, "test-model", 1000)

    with pytest.raises(PlanValidationError, match="unknown action"):
        engine.respond([], "do something")


def test_llm_request_error_propagates_uncaught(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(error=LLMRequestError("connection refused", retryable=True))
    engine = ConversationEngine(client, registry, "test-model", 1000)

    with pytest.raises(LLMRequestError):
        engine.respond([], "hello")
