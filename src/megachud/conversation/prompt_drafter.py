from __future__ import annotations

from dataclasses import dataclass

from megachud.llm.client import LLMClient

__all__ = ["PromptDraftResult", "PromptDrafter"]

_SYSTEM_PROMPT = (
    "You turn a user's rough, informal notes into a single, clear, "
    "well-specified task prompt for an autonomous execution system. "
    "Preserve the user's actual intent and every concrete detail they "
    "gave (file names, URLs, exact wording, numbers) — do not invent "
    "requirements they didn't state. Respond with ONLY the rewritten "
    "prompt text: no preamble, no quotes, no markdown fences, no "
    "explanation of what you did."
)


@dataclass
class PromptDraftResult:
    prompt: str
    tokens_input: int
    tokens_output: int
    model: str


class PromptDrafter:
    """One-shot, stateless: turns rough input text into a clean task
    prompt the user can then hand to Auto/Semi-Manual/Full-Manual mode.
    Plain-text completion (tool=None) — the output is a single string,
    not multiple structured fields, so forced tool-use would be needless
    structure (AnthropicLLMClient reserves forced tool-use for
    *structured* output that needs server-side schema validation). This
    is the first plain-text LLM consumer in this codebase — every other
    one (reflection/curiosity/planner/conversation) passes a tool schema.
    """

    def __init__(self, client: LLMClient, model: str, max_tokens: int) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def draft(self, raw_text: str) -> PromptDraftResult:
        # LLMError/LLMRequestError propagate uncaught — matches
        # LLMTaskPlanner.plan()'s convention: a genuinely new capability
        # with no deterministic fallback, not a graceful-degradation
        # consumer like reflection/curiosity. The route decides how to
        # surface a failure.
        response = self._client.complete(
            model=self._model,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": raw_text}],
            max_tokens=self._max_tokens,
        )
        return PromptDraftResult(
            prompt=response.text.strip(),
            tokens_input=response.tokens_input,
            tokens_output=response.tokens_output,
            model=response.model,
        )
