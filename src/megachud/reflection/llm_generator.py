from __future__ import annotations

import json

from megachud.events.logger import EventLogger
from megachud.llm.client import LLMClient, LLMError
from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.task import Task
from megachud.reflection.generator import DeterministicReflectionGenerator, ReflectionDraft, ReflectionGenerator
from megachud.routing.engine import ModelProfile, compute_cost_usd
from megachud.runtime.thoughts import ThoughtLog

_TOOL_SCHEMA = {
    "name": "submit_reflection",
    "description": "Submit a structured reflection on how a completed task went.",
    "input_schema": {
        "type": "object",
        "properties": {
            "what_worked": {"type": "array", "items": {"type": "string"}},
            "what_failed": {"type": "array", "items": {"type": "string"}},
            "wrong_assumptions": {"type": "array", "items": {"type": "string"}},
            "should_change": {"type": "array", "items": {"type": "string"}},
            "become_long_term_knowledge": {"type": "boolean"},
        },
        "required": ["what_worked", "what_failed", "wrong_assumptions", "should_change", "become_long_term_knowledge"],
    },
}

_SYSTEM_PROMPT = (
    "You analyze a completed automated task and produce a structured reflection. "
    "Base every statement strictly on the task/evaluation/event data given to you — "
    "never invent facts, tool names, or outcomes not present in that data. "
    "what_worked and what_failed should reference specific checks or tool calls. "
    "wrong_assumptions should name assumptions the task's plan implicitly made that "
    "turned out false, if any. should_change should be concrete, actionable process "
    "changes, not vague advice. Empty lists are fine and preferred over invented content. "
    "become_long_term_knowledge should be true if this task's outcome (success or "
    "failure) contains a lesson worth remembering for similar future tasks."
)


class LLMReflectionGenerator(ReflectionGenerator):
    """Smallest, safest LLM swap-point: never raises out of generate() —
    any LLM failure or malformed response falls back to a deterministic
    implementation, so ReflectionEngine.reflect() always succeeds exactly
    as it does today.
    """

    def __init__(
        self,
        client: LLMClient,
        model: str,
        profiles: list[ModelProfile],
        max_tokens: int,
        event_logger: EventLogger,
        fallback: ReflectionGenerator | None = None,
        thought_log: ThoughtLog | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._profiles = profiles
        self._max_tokens = max_tokens
        self._event_logger = event_logger
        self._fallback = fallback or DeterministicReflectionGenerator()
        self._thought_log = thought_log

    def generate(self, task: Task, evaluation: Evaluation | None, events: list[Event]) -> ReflectionDraft:
        try:
            response = self._client.complete(
                model=self._model,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": self._build_prompt(task, evaluation, events)}],
                max_tokens=self._max_tokens,
                tool=_TOOL_SCHEMA,
            )
        except LLMError:
            return self._fallback.generate(task, evaluation, events)

        if not response.raw_tool_calls:
            return self._fallback.generate(task, evaluation, events)

        try:
            data = response.raw_tool_calls[0]["input"]
            draft = ReflectionDraft(
                what_worked=list(data["what_worked"]),
                what_failed=list(data["what_failed"]),
                wrong_assumptions=list(data["wrong_assumptions"]),
                should_change=list(data["should_change"]),
                become_long_term_knowledge=bool(data["become_long_term_knowledge"]),
            )
        except (KeyError, TypeError):
            return self._fallback.generate(task, evaluation, events)

        self._log_cost(task.id, response.model, response.tokens_input, response.tokens_output)
        if self._thought_log is not None and draft.should_change:
            self._thought_log.record("reflection", f"On '{task.title}', I'd change: {draft.should_change[0]}")
        return draft

    def _build_prompt(self, task: Task, evaluation: Evaluation | None, events: list[Event]) -> str:
        lines = [
            f"Task title: {task.title}",
            f"Task prompt: {task.prompt}",
            f"Retry count: {task.retry_count}",
        ]
        if evaluation is not None:
            lines.append("Evaluation checks:")
            for check in json.loads(evaluation.checks_json):
                lines.append(f"  - {check['name']}: passed={check['passed']} detail={check['detail']}")
        else:
            lines.append(f"Evaluation: none (task result_summary: {task.result_summary!r})")

        lines.append("Events:")
        for event in events:
            if event.event_type not in ("tool_call", "tool_result"):
                continue
            payload = json.loads(event.payload_json)
            lines.append(f"  - {event.event_type} tool={event.tool_name} payload={payload}")

        return "\n".join(lines)

    def _log_cost(self, task_id: str, model: str, tokens_input: int, tokens_output: int) -> None:
        profile = next((p for p in self._profiles if p.name == model), None)
        cost_usd = compute_cost_usd(profile, tokens_input, tokens_output) if profile is not None else None
        self._event_logger.log(
            event_type="llm_call",
            task_id=task_id,
            tool_name="llm:reflection",
            cost_usd=cost_usd,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            payload={"model": model, "consumer": "reflection"},
        )
