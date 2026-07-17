from __future__ import annotations

from dataclasses import dataclass

from megachud.llm.client import LLMClient
from megachud.orchestrator.task_models import ToolCall
from megachud.tools.base import ToolValidationError
from megachud.tools.registry import ToolRegistry

_SYSTEM_PROMPT_TEMPLATE = (
    "You plan a sequence of tool calls to accomplish an objective, for a "
    "system that then executes the plan exactly as given — you do not see "
    "the results and cannot revise the plan afterward, so make it complete "
    "and correct in one shot. Only use tools from the catalog below, with "
    "args matching what each tool expects. Prefer the minimum number of "
    "steps that accomplishes the objective.\n\nAvailable tools:\n{catalog}"
)


@dataclass
class PlanResult:
    plan: list[ToolCall]
    tokens_input: int
    tokens_output: int
    model: str


class PlanValidationError(Exception):
    """Raised when the LLM's plan references an unknown tool, fails
    Tool.validate_args, or is otherwise malformed — caught by the API
    route, turned into a 422, and the Task row is never created.
    """


class LLMTaskPlanner:
    """One-shot planning only — no re-prompting, no iteration. A single
    LLM call proposes a full plan; a single validation pass either
    accepts or rejects it whole. This is deliberately NOT an iterative/
    agentic loop: the produced plan runs through the existing
    Orchestrator.run_task completely unchanged, preserving the "no
    re-planning loop, no runaway-agent risk" property every prior phase
    has relied on.
    """

    def __init__(self, client: LLMClient, tool_registry: ToolRegistry, model: str, max_tokens: int) -> None:
        self._client = client
        self._tool_registry = tool_registry
        self._model = model
        self._max_tokens = max_tokens

    def plan(self, prompt: str) -> PlanResult:
        tools = self._tool_registry.all()
        tool_names = [t.name for t in tools]
        catalog = "\n".join(f"- {t.name} (risk_level={t.risk_level.value}): {t.description}" for t in tools)

        schema = {
            "name": "submit_plan",
            "description": "Submit the ordered list of tool calls needed to accomplish the objective.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool_name": {"type": "string", "enum": tool_names},
                                "args": {"type": "object"},
                            },
                            "required": ["tool_name", "args"],
                        },
                    }
                },
                "required": ["steps"],
            },
        }

        # LLMError propagates uncaught — the API route converts it to a
        # clean error response. Unlike reflection/curiosity, planning has
        # no deterministic fallback to degrade to: a plan that silently
        # became "no plan" would be more confusing than a clean error.
        response = self._client.complete(
            model=self._model,
            system=_SYSTEM_PROMPT_TEMPLATE.format(catalog=catalog),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self._max_tokens,
            tool=schema,
        )

        if not response.raw_tool_calls:
            raise PlanValidationError("LLM did not return a tool_use plan")

        steps = response.raw_tool_calls[0]["input"].get("steps")
        if not steps:
            raise PlanValidationError("LLM returned an empty plan")

        validated: list[ToolCall] = []
        for step in steps:
            tool_name = step.get("tool_name")
            args = step.get("args") or {}
            # The JSON-schema enum on tool_name is the first validation
            # line (Anthropic rejects an unknown name before it's even
            # returned); ToolRegistry.get() + Tool.validate_args() is the
            # authoritative second line — the exact validation the
            # orchestrator would eventually hit, performed before any
            # Task row exists.
            try:
                tool = self._tool_registry.get(tool_name)
            except KeyError as exc:
                raise PlanValidationError(f"plan references unknown tool: {tool_name!r}") from exc
            try:
                tool.validate_args(args)
            except ToolValidationError as exc:
                raise PlanValidationError(f"invalid args for tool {tool_name!r}: {exc}") from exc
            validated.append(ToolCall(tool_name=tool_name, args=args))

        return PlanResult(
            plan=validated,
            tokens_input=response.tokens_input,
            tokens_output=response.tokens_output,
            model=response.model,
        )
