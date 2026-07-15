from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from megachud.evaluation.engine import EvaluationEngine
from megachud.events.logger import EventLogger
from megachud.models.approval import RiskLevel
from megachud.models.task import Task, TaskStatus
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.orchestrator.retries import RetryPolicy
from megachud.orchestrator.task_models import ToolCall
from megachud.tools.base import ToolResult
from megachud.tools.registry import ToolRegistry


class Orchestrator:
    """Phase 1 execution loop. A Task carries a caller-supplied, finite
    `plan_json` (list of ToolCall) — there is no autonomous re-planning loop
    yet, so runaway agent loops are structurally impossible at this phase.
    An LLM-driven planner can replace the caller-supplied plan later without
    changing this loop's shape.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        tool_registry: ToolRegistry,
        approval_gate: ApprovalGate,
        evaluator: EvaluationEngine,
        event_logger: EventLogger,
        workspace_root: Path,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._tool_registry = tool_registry
        self._approval_gate = approval_gate
        self._evaluator = evaluator
        self._event_logger = event_logger
        self._workspace_root = workspace_root
        self._retry_policy = retry_policy or RetryPolicy()

    def run_task(self, task_id: str) -> Task:
        plan = self._start_task(task_id)
        self._event_logger.log(event_type="task_started", task_id=task_id, payload={"plan_length": len(plan)})

        step_results: list[ToolResult] = []
        for call in plan:
            tool = self._tool_registry.get(call.tool_name)

            if tool.risk_level == RiskLevel.HIGH_IRREVERSIBLE:
                decision = self._approval_gate.request_and_wait(task_id, tool, call.args)
                if not decision.approved:
                    return self._fail_task(task_id, f"approval not granted for {tool.name}: {decision.status.value}")
                self._set_status(task_id, TaskStatus.RUNNING)

            result = self._execute_with_retry(task_id, tool, call)
            step_results.append(result)

            if not result.success:
                return self._fail_task(task_id, f"tool {tool.name} failed: {result.error}")

        return self._evaluate_and_finish(task_id, step_results)

    def _execute_with_retry(self, task_id: str, tool, call: ToolCall) -> ToolResult:
        result: ToolResult | None = None
        for attempt in range(self._retry_policy.max_attempts):
            start = time.monotonic()
            result = tool.run(call.args)
            duration_ms = int((time.monotonic() - start) * 1000)

            self._event_logger.log(
                event_type="tool_call",
                task_id=task_id,
                tool_name=tool.name,
                duration_ms=duration_ms,
                payload={"args": call.args, "attempt": attempt + 1},
            )
            self._event_logger.log(
                event_type="tool_result",
                task_id=task_id,
                tool_name=tool.name,
                duration_ms=duration_ms,
                payload={"success": result.success, "output": result.output[:2000], "error": result.error},
            )

            if result.success:
                return result

            if attempt + 1 < self._retry_policy.max_attempts:
                time.sleep(self._retry_policy.backoff_for(attempt))

        assert result is not None
        return result

    def _evaluate_and_finish(self, task_id: str, step_results: list[ToolResult]) -> Task:
        task = self._get_task(task_id)
        evaluation = self._evaluator.evaluate(task, step_results, self._workspace_root)

        session = self._session_factory()
        try:
            session.add(evaluation)
            session.commit()
            session.refresh(evaluation)
            evaluation_id = evaluation.id
            success = evaluation.success
        finally:
            session.close()

        self._event_logger.log(
            event_type="evaluation",
            task_id=task_id,
            evaluation_id=evaluation_id,
            payload={"success": success},
        )

        final_status = TaskStatus.SUCCEEDED if success else TaskStatus.FAILED
        summary = "evaluation passed" if success else "evaluation failed"
        finished = self._finish_task(task_id, final_status, summary)
        self._event_logger.log(
            event_type="task_completed" if success else "task_failed",
            task_id=task_id,
            payload={},
        )
        return finished

    def _fail_task(self, task_id: str, reason: str) -> Task:
        finished = self._finish_task(task_id, TaskStatus.FAILED, reason)
        self._event_logger.log(event_type="task_failed", task_id=task_id, payload={"reason": reason})
        return finished

    def _start_task(self, task_id: str) -> list[ToolCall]:
        session = self._session_factory()
        try:
            task = session.get(Task, task_id)
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(timezone.utc)
            plan_raw = json.loads(task.plan_json)
            session.commit()
            return [ToolCall(**item) for item in plan_raw]
        finally:
            session.close()

    def _set_status(self, task_id: str, status: TaskStatus) -> None:
        session = self._session_factory()
        try:
            task = session.get(Task, task_id)
            task.status = status
            session.commit()
        finally:
            session.close()

    def _finish_task(self, task_id: str, status: TaskStatus, result_summary: str) -> Task:
        session = self._session_factory()
        try:
            task = session.get(Task, task_id)
            task.status = status
            task.completed_at = datetime.now(timezone.utc)
            task.result_summary = result_summary
            session.commit()
            session.refresh(task)
            session.expunge(task)
            return task
        finally:
            session.close()

    def _get_task(self, task_id: str) -> Task:
        session = self._session_factory()
        try:
            task = session.get(Task, task_id)
            session.expunge(task)
            return task
        finally:
            session.close()
