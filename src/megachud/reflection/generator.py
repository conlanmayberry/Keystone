from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.task import Task


@dataclass
class ReflectionDraft:
    what_worked: list[str]
    what_failed: list[str]
    wrong_assumptions: list[str]
    should_change: list[str]
    become_long_term_knowledge: bool


class ReflectionGenerator(ABC):
    """Swap point: an LLM-backed implementation can replace
    DeterministicReflectionGenerator later without touching ReflectionEngine,
    the orchestrator, or any other caller — only api/app.py's wiring changes,
    mirroring how Tool.risk_level lets future tools slot in without
    orchestrator rework.
    """

    @abstractmethod
    def generate(self, task: Task, evaluation: Evaluation | None, events: list[Event]) -> ReflectionDraft:
        ...


class DeterministicReflectionGenerator(ReflectionGenerator):
    """No LLM call. Every line is derived from Evaluation.checks_json,
    Event rows, and Task fields — never fabricated. `evaluation` is None
    whenever a task failed before evaluation ever ran (approval denied, or
    a tool call failed) — every rule below tolerates that.
    """

    def generate(self, task: Task, evaluation: Evaluation | None, events: list[Event]) -> ReflectionDraft:
        what_failed = self._what_failed(task, evaluation, events)
        wrong_assumptions = self._wrong_assumptions(task, evaluation, what_failed)
        return ReflectionDraft(
            what_worked=self._what_worked(task, evaluation),
            what_failed=what_failed,
            wrong_assumptions=wrong_assumptions,
            should_change=self._should_change(evaluation, wrong_assumptions, what_failed),
            become_long_term_knowledge=self._become_long_term_knowledge(evaluation, wrong_assumptions),
        )

    def _what_worked(self, task: Task, evaluation: Evaluation | None) -> list[str]:
        lines: list[str] = []
        if evaluation is not None:
            for check in json.loads(evaluation.checks_json):
                if check["passed"]:
                    lines.append(f"{check['name']}: {check['detail']}")
        if task.retry_count == 0:
            lines.append("completed without retries")
        return lines

    def _what_failed(self, task: Task, evaluation: Evaluation | None, events: list[Event]) -> list[str]:
        lines: list[str] = []
        if evaluation is not None:
            for check in json.loads(evaluation.checks_json):
                if not check["passed"]:
                    lines.append(f"{check['name']}: {check['detail']}")
        elif task.result_summary:
            lines.append(task.result_summary)

        for event in events:
            if event.event_type != "tool_result":
                continue
            payload = json.loads(event.payload_json)
            if payload.get("success") is False:
                lines.append(f"{event.tool_name} failed: {payload.get('error')}")
        return lines

    def _wrong_assumptions(self, task: Task, evaluation: Evaluation | None, what_failed: list[str]) -> list[str]:
        assumptions: list[str] = []
        failed_text = " ".join(what_failed)

        if evaluation is not None:
            for check in json.loads(evaluation.checks_json):
                if check["name"] == "python_syntax" and not check["passed"]:
                    assumptions.append("assumed generated code would be syntactically valid")

        if "escapes workspace" in failed_text or "WorkspaceEscapeError" in failed_text:
            assumptions.append("assumed a provided path stayed within the workspace")

        if task.retry_count > 0:
            assumptions.append("assumed the first tool-call attempt would succeed")

        if task.result_summary and "approval" in task.result_summary.lower():
            assumptions.append("assumed the requested action would be approved")

        return assumptions

    def _should_change(self, evaluation: Evaluation | None, wrong_assumptions: list[str], what_failed: list[str]) -> list[str]:
        changes: list[str] = []

        if evaluation is not None:
            for check in json.loads(evaluation.checks_json):
                if check["passed"]:
                    continue
                if check["name"] == "python_syntax":
                    changes.append("validate generated code compiles before writing")
                elif check["name"] == "tests_pass":
                    changes.append("run tests before marking a task complete")

        if any("workspace" in a for a in wrong_assumptions):
            changes.append("validate paths against the workspace before use")
        if any("first tool-call attempt" in a for a in wrong_assumptions):
            changes.append("add pre-flight validation to reduce retries")
        if any("approved" in a for a in wrong_assumptions):
            changes.append("clarify approval requirements before requesting high-risk actions")

        if not changes and not what_failed:
            changes = ["no change indicated"]
        return changes

    def _become_long_term_knowledge(self, evaluation: Evaluation | None, wrong_assumptions: list[str]) -> bool:
        succeeded = evaluation is not None and evaluation.success
        return (not succeeded) or len(wrong_assumptions) > 0
