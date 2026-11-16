from __future__ import annotations

from dataclasses import dataclass

from megachud.llm.client import LLMClient
from megachud.obsidian.guidance import GuidanceLoader, with_guidance
from megachud.orchestrator.plan_validation import PlanValidationError, validate_plan_steps
from megachud.orchestrator.task_models import ToolCall
from megachud.routing.selector import ModelSelector
from megachud.tools.registry import ToolRegistry

__all__ = ["PlanResult", "PlanValidationError", "LLMTaskPlanner"]

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
    model_reason: str = "default"


class LLMTaskPlanner:
    """One-shot planning only — no re-prompting, no iteration. A single
    LLM call proposes a full plan; a single validation pass (shared with
    ConversationEngine via orchestrator.plan_validation) either accepts or
    rejects it whole. This is deliberately NOT an iterative/agentic loop:
    the produced plan runs through the existing Orchestrator.run_task
    completely unchanged, preserving the "no re-planning loop, no
    runaway-agent risk" property every prior phase has relied on.
    """

    def __init__(
        self,
        client: LLMClient,
        tool_registry: ToolRegistry,
        model: str,
        max_tokens: int,
        selector: ModelSelector | None = None,
        guidance_loader: GuidanceLoader | None = None,
    ) -> None:
        self._client = client
        self._tool_registry = tool_registry
        self._model = model
        self._max_tokens = max_tokens
        self._selector = selector
        self._guidance_loader = guidance_loader

    def plan(self, prompt: str, model: str | None = None) -> PlanResult:
        chosen_model, model_reason = self._resolve_model(prompt, model)
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
        # Rebuilt per call, not cached: the point of vault-held guidance is
        # that editing a note changes the next run with no restart.
        guidance = self._guidance_loader.load("planner") if self._guidance_loader is not None else ""
        system = with_guidance(_SYSTEM_PROMPT_TEMPLATE.format(catalog=catalog), guidance)

        response = self._client.complete(
            model=chosen_model,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self._max_tokens,
            tool=schema,
        )

        if not response.raw_tool_calls:
            raise PlanValidationError("LLM did not return a tool_use plan")

        steps = response.raw_tool_calls[0]["input"].get("steps")
        validated = validate_plan_steps(steps, self._tool_registry)

        return PlanResult(
            plan=validated,
            tokens_input=response.tokens_input,
            tokens_output=response.tokens_output,
            model=response.model,
            model_reason=model_reason,
        )

    def _resolve_model(self, prompt: str, override: str | None) -> tuple[str, str]:
        if self._selector is not None:
            return self._selector.select(prompt, override=override)
        if override:
            return override, "manual override"
        return self._model, "default"
