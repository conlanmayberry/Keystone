from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from megachud.llm.client import LLMClient
from megachud.orchestrator.plan_validation import PlanValidationError, validate_plan_steps
from megachud.orchestrator.task_models import ToolCall
from megachud.routing.selector import ModelSelector
from megachud.tools.registry import ToolRegistry

__all__ = ["ConversationTurnResult", "ConversationEngine"]

_SYSTEM_PROMPT_TEMPLATE = (
    "You are a conversational assistant that helps a user define a task for "
    "an autonomous execution system. Ask clarifying questions "
    "(action=\"ask_question\") when the objective is ambiguous or missing "
    "required detail. Once you have enough information, respond with "
    "action=\"propose_plan\" plus a complete `steps` list: the system then "
    "executes an approved plan exactly as given, in one shot — you will not "
    "see the results and cannot revise it afterward, so only propose a plan "
    "once it is complete and correct. Only use tools from the catalog "
    "below, with args matching what each tool expects.\n\n"
    "Available tools:\n{catalog}"
)


@dataclass
class ConversationTurnResult:
    action: Literal["ask_question", "propose_plan"]
    message: str
    plan: list[ToolCall] | None  # None iff action == "ask_question"
    tokens_input: int
    tokens_output: int
    model: str
    model_reason: str = "default"


class ConversationEngine:
    """One forced-tool-use LLM call per respond() invocation. Multi-turn is
    entirely a property of the CALLER invoking this repeatedly (once per
    human message, with the growing history passed back in) — this class
    has no notion of a running task, never sees tool results, and never
    revises a plan after the fact. Mirrors LLMTaskPlanner's one-shot-per-
    call discipline exactly; the only difference is this call can also
    choose to ask a question instead of proposing a plan.

    `history` passed to respond() must be plain conversation text only —
    prior user/assistant message content, never tool-call results, never
    a previously-proposed plan's raw JSON. That's what keeps the LLM from
    ever "seeing what happened" and revising a plan: that information
    structurally never enters the messages sent to it.
    """

    def __init__(
        self,
        client: LLMClient,
        tool_registry: ToolRegistry,
        model: str,
        max_tokens: int,
        selector: ModelSelector | None = None,
    ) -> None:
        self._client = client
        self._tool_registry = tool_registry
        self._model = model
        self._max_tokens = max_tokens
        self._selector = selector

    def respond(
        self, history: list[dict[str, str]], user_message: str, model: str | None = None
    ) -> ConversationTurnResult:
        chosen_model, model_reason = self._resolve_model(user_message, model)
        tools = self._tool_registry.all()
        tool_names = [t.name for t in tools]
        catalog = "\n".join(f"- {t.name} (risk_level={t.risk_level.value}): {t.description}" for t in tools)

        schema = {
            "name": "conversation_turn",
            "description": "Respond to the user: ask a clarifying question, or propose a finished plan.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["ask_question", "propose_plan"]},
                    "message": {
                        "type": "string",
                        "description": "The clarifying question, or a plain-language summary of the proposed plan for the user to read.",
                    },
                    "steps": {
                        "type": "array",
                        "description": "Required when action is propose_plan; omit otherwise.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool_name": {"type": "string", "enum": tool_names},
                                "args": {"type": "object"},
                            },
                            "required": ["tool_name", "args"],
                        },
                    },
                },
                "required": ["action", "message"],
            },
        }

        # LLMError/LLMRequestError propagate uncaught — same convention as
        # LLMTaskPlanner.plan(); the API route decides how to surface it
        # (and must do so without leaving a dangling unanswered turn, since
        # Anthropic's Messages API requires strict user/assistant
        # alternation for the NEXT call to succeed).
        response = self._client.complete(
            model=chosen_model,
            system=_SYSTEM_PROMPT_TEMPLATE.format(catalog=catalog),
            messages=[*history, {"role": "user", "content": user_message}],
            max_tokens=self._max_tokens,
            tool=schema,
        )

        if not response.raw_tool_calls:
            raise PlanValidationError("LLM did not return a conversation_turn response")

        turn = response.raw_tool_calls[0]["input"]
        action = turn.get("action")
        message = turn.get("message") or ""

        if action == "ask_question":
            return ConversationTurnResult(
                "ask_question", message, None, response.tokens_input, response.tokens_output, response.model, model_reason
            )
        if action == "propose_plan":
            validated = validate_plan_steps(turn.get("steps"), self._tool_registry)
            return ConversationTurnResult(
                "propose_plan", message, validated, response.tokens_input, response.tokens_output, response.model, model_reason
            )
        raise PlanValidationError(f"LLM returned unknown action: {action!r}")

    def _resolve_model(self, prompt: str, override: str | None) -> tuple[str, str]:
        if self._selector is not None:
            return self._selector.select(prompt, override=override)
        if override:
            return override, "manual override"
        return self._model, "default"
