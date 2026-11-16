"""Guidance reaching the two non-research LLM consumers. The research
path is covered in test_obsidian_guidance.py.
"""

from __future__ import annotations

from megachud.conversation.engine import ConversationEngine
from megachud.llm.client import LLMResponse
from megachud.obsidian.guidance import GuidanceLoader
from megachud.orchestrator.llm_planner import LLMTaskPlanner
from megachud.tools.file_tools import ReadFileTool
from megachud.tools.registry import ToolRegistry
from tests.fixtures.fake_llm_client import FakeLLMClient


def write_guidance(vault, name: str, text: str) -> None:
    folder = vault / "guidance"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def make_registry(tmp_workspace) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool(tmp_workspace))
    return registry


def plan_response() -> LLMResponse:
    return LLMResponse(
        text="", tokens_input=10, tokens_output=10, model="m", stop_reason="tool_use",
        raw_tool_calls=[{"name": "submit_plan", "input": {"steps": [{"tool_name": "read_file", "args": {"path": "a.txt"}}]}}],
    )


def turn_response() -> LLMResponse:
    return LLMResponse(
        text="", tokens_input=10, tokens_output=10, model="m", stop_reason="tool_use",
        raw_tool_calls=[{"name": "conversation_turn", "input": {"action": "ask_question", "message": "which file?"}}],
    )


def test_planner_receives_planner_scoped_guidance(tmp_vault, tmp_workspace):
    write_guidance(tmp_vault, "Planning.md", "---\napplies_to: [planner]\n---\n\nOrder steps by risk.")
    write_guidance(tmp_vault, "Linking.md", "---\napplies_to: [research]\n---\n\nLink sparingly.")
    client = FakeLLMClient(response=plan_response())
    planner = LLMTaskPlanner(
        client, make_registry(tmp_workspace), model="m", max_tokens=512, guidance_loader=GuidanceLoader(tmp_vault)
    )

    planner.plan("do a thing")

    system = client.calls[0]["system"]
    assert "Order steps by risk." in system
    # Research-output rules would be pure context cost to the planner.
    assert "Link sparingly." not in system
    # The tool catalog and the one-shot rules survive underneath.
    assert "Available tools:" in system


def test_conversation_receives_conversation_scoped_guidance(tmp_vault, tmp_workspace):
    write_guidance(tmp_vault, "Talking.md", "---\napplies_to: [conversation]\n---\n\nOne question at a time.")
    client = FakeLLMClient(response=turn_response())
    engine = ConversationEngine(
        client, make_registry(tmp_workspace), model="m", max_tokens=512, guidance_loader=GuidanceLoader(tmp_vault)
    )

    engine.respond([], "help me")

    assert "One question at a time." in client.calls[0]["system"]


def test_guidance_sits_below_the_hardcoded_rules(tmp_vault, tmp_workspace):
    write_guidance(tmp_vault, "Rules.md", "Order steps by risk.")
    client = FakeLLMClient(response=plan_response())
    planner = LLMTaskPlanner(
        client, make_registry(tmp_workspace), model="m", max_tokens=512, guidance_loader=GuidanceLoader(tmp_vault)
    )

    planner.plan("do a thing")

    system = client.calls[0]["system"]
    # A note must never be positioned to override the consumer's own rules.
    assert system.index("You plan a sequence of tool calls") < system.index("Order steps by risk.")
    assert "the rules above win" in system


def test_no_guidance_loader_leaves_prompts_unchanged(tmp_vault, tmp_workspace):
    client = FakeLLMClient(response=plan_response())
    planner = LLMTaskPlanner(client, make_registry(tmp_workspace), model="m", max_tokens=512)

    planner.plan("do a thing")

    assert "the rules above win" not in client.calls[0]["system"]


def test_empty_guidance_folder_leaves_prompts_unchanged(tmp_vault, tmp_workspace):
    (tmp_vault / "guidance").mkdir()
    client = FakeLLMClient(response=turn_response())
    engine = ConversationEngine(
        client, make_registry(tmp_workspace), model="m", max_tokens=512, guidance_loader=GuidanceLoader(tmp_vault)
    )

    engine.respond([], "help me")

    assert "the rules above win" not in client.calls[0]["system"]
