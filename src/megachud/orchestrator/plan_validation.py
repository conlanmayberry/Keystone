from __future__ import annotations

from megachud.orchestrator.task_models import ToolCall
from megachud.tools.base import ToolValidationError
from megachud.tools.registry import ToolRegistry


class PlanValidationError(Exception):
    """Raised when a set of proposed steps (from LLMTaskPlanner or
    ConversationEngine) references an unknown tool, fails
    Tool.validate_args, or is empty/missing — the one validation authority
    every planner-shaped LLM consumer shares."""


def validate_plan_steps(steps: list[dict] | None, tool_registry: ToolRegistry) -> list[ToolCall]:
    """Validate and convert LLM-proposed {tool_name, args} steps into
    ToolCalls. The JSON-schema enum on tool_name that callers put in their
    forced-tool-use schema is the first validation line (the LLM provider
    rejects an unknown name before it's even returned); this is the
    authoritative second line — the exact validation the orchestrator
    would eventually hit, performed before any Task row exists.
    """
    if not steps:
        raise PlanValidationError("LLM returned an empty plan")

    validated: list[ToolCall] = []
    for step in steps:
        tool_name = step.get("tool_name")
        args = step.get("args") or {}
        try:
            tool = tool_registry.get(tool_name)
        except KeyError as exc:
            raise PlanValidationError(f"plan references unknown tool: {tool_name!r}") from exc
        try:
            tool.validate_args(args)
        except ToolValidationError as exc:
            raise PlanValidationError(f"invalid args for tool {tool_name!r}: {exc}") from exc
        validated.append(ToolCall(tool_name=tool_name, args=args))
    return validated
