from __future__ import annotations

from megachud.llm.client import LLMResponse
from megachud.orchestrator.llm_planner import LLMTaskPlanner, PlanValidationError
from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry
from tests.fixtures.fake_llm_client import FakeLLMClient
import pytest


def make_registry(tmp_workspace) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool(tmp_workspace))
    registry.register(WriteFileTool(tmp_workspace))
    return registry


def response_with_steps(steps: list[dict]) -> LLMResponse:
    return LLMResponse(
        text="", tokens_input=50, tokens_output=30, model="test-model", stop_reason="tool_use",
        raw_tool_calls=[{"name": "submit_plan", "input": {"steps": steps}}],
    )


def test_happy_path_produces_validated_plan(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=response_with_steps([
        {"tool_name": "write_file", "args": {"path": "a.txt", "content": "hi"}},
        {"tool_name": "read_file", "args": {"path": "a.txt"}},
    ]))
    planner = LLMTaskPlanner(client, registry, "test-model", 1000)

    result = planner.plan("write and read a file")

    assert len(result.plan) == 2
    assert result.plan[0].tool_name == "write_file"
    assert result.plan[0].args == {"path": "a.txt", "content": "hi"}
    assert result.tokens_input == 50
    assert result.tokens_output == 30
    assert result.model == "test-model"


def test_hallucinated_tool_name_raises_plan_validation_error(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=response_with_steps([{"tool_name": "delete_universe", "args": {}}]))
    planner = LLMTaskPlanner(client, registry, "test-model", 1000)

    with pytest.raises(PlanValidationError, match="unknown tool"):
        planner.plan("do something impossible")


def test_malformed_args_raises_plan_validation_error(tmp_workspace):
    registry = make_registry(tmp_workspace)
    # write_file requires 'content'; omit it to trip real Tool.validate_args.
    client = FakeLLMClient(response=response_with_steps([{"tool_name": "write_file", "args": {"path": "a.txt"}}]))
    planner = LLMTaskPlanner(client, registry, "test-model", 1000)

    with pytest.raises(PlanValidationError, match="invalid args"):
        planner.plan("write a file")


def test_empty_steps_raises_plan_validation_error(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=response_with_steps([]))
    planner = LLMTaskPlanner(client, registry, "test-model", 1000)

    with pytest.raises(PlanValidationError, match="empty plan"):
        planner.plan("do nothing")


def test_no_tool_use_in_response_raises_plan_validation_error(tmp_workspace):
    registry = make_registry(tmp_workspace)
    client = FakeLLMClient(response=LLMResponse(text="I refuse", tokens_input=5, tokens_output=5, model="test-model", stop_reason="end_turn"))
    planner = LLMTaskPlanner(client, registry, "test-model", 1000)

    with pytest.raises(PlanValidationError, match="did not return a tool_use"):
        planner.plan("do something")
