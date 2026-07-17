from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from megachud.llm.client import LLMClient, LLMError


@dataclass
class CuriosityText:
    question: str
    objective_descriptions: dict[str, str] = field(default_factory=dict)
    # 0/None for the deterministic generator — CuriosityHandler never logs
    # a misleading llm_call cost event for the fully-local path.
    tokens_input: int = 0
    tokens_output: int = 0
    model: str | None = None


class CuriosityTextGenerator(ABC):
    @abstractmethod
    def generate(
        self, task_title: str, task_prompt: str, best_prior_similarity: float, similarity_threshold: float
    ) -> CuriosityText: ...


class DeterministicCuriosityTextGenerator(CuriosityTextGenerator):
    """Extracted verbatim from CuriosityHandler's original inline template
    strings — behavior-preserving; existing test_curiosity_engine.py text
    assertions keep passing unchanged.
    """

    def generate(
        self, task_title: str, task_prompt: str, best_prior_similarity: float, similarity_threshold: float
    ) -> CuriosityText:
        return CuriosityText(
            question=(
                f"Task {task_title!r} produced a lesson with no close precedent "
                f"(best prior similarity {best_prior_similarity:.2f} below threshold {similarity_threshold}). "
                "What is the right general approach for similar future tasks?"
            ),
            objective_descriptions={
                "search_memory": f"search_memory for: {task_prompt[:200]}",
                "inspect_previous_work": f"inspect_previous_work for: {task_title[:200]}",
            },
        )


_TOOL_SCHEMA = {
    "name": "submit_curiosity_text",
    "description": "Submit the question and research-objective descriptions for a novel task outcome.",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "search_memory_description": {"type": "string"},
            "inspect_previous_work_description": {"type": "string"},
        },
        "required": ["question", "search_memory_description", "inspect_previous_work_description"],
    },
}

_SYSTEM_PROMPT = (
    "A task's outcome was flagged as worth remembering, but no closely similar "
    "past memory exists. Write a concise question asking what the right general "
    "approach is for similar future tasks, and two short descriptions of what to "
    "look into: a broad memory search, and inspecting similar past episodic work. "
    "Base this only on the task title/prompt given — do not invent specifics not "
    "present in them."
)


class LLMCuriosityTextGenerator(CuriosityTextGenerator):
    def __init__(
        self, client: LLMClient, model: str, max_tokens: int, fallback: CuriosityTextGenerator | None = None
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._fallback = fallback or DeterministicCuriosityTextGenerator()

    def generate(
        self, task_title: str, task_prompt: str, best_prior_similarity: float, similarity_threshold: float
    ) -> CuriosityText:
        try:
            response = self._client.complete(
                model=self._model,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"Task title: {task_title}\nTask prompt: {task_prompt}"}],
                max_tokens=self._max_tokens,
                tool=_TOOL_SCHEMA,
            )
        except LLMError:
            return self._fallback.generate(task_title, task_prompt, best_prior_similarity, similarity_threshold)

        if not response.raw_tool_calls:
            return self._fallback.generate(task_title, task_prompt, best_prior_similarity, similarity_threshold)

        try:
            data = response.raw_tool_calls[0]["input"]
            return CuriosityText(
                question=str(data["question"]),
                objective_descriptions={
                    "search_memory": str(data["search_memory_description"]),
                    "inspect_previous_work": str(data["inspect_previous_work_description"]),
                },
                tokens_input=response.tokens_input,
                tokens_output=response.tokens_output,
                model=response.model,
            )
        except (KeyError, TypeError):
            return self._fallback.generate(task_title, task_prompt, best_prior_similarity, similarity_threshold)
