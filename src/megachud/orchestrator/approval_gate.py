from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from megachud.events.logger import EventLogger
from megachud.models.approval import ApprovalRequest, ApprovalStatus
from megachud.models.task import Task, TaskStatus
from megachud.tools.base import Tool


@dataclass
class ApprovalDecision:
    approved: bool
    status: ApprovalStatus
    note: str | None = None


class ApprovalGate:
    """Concrete mechanism for spec principle #8 ("human approval is required
    for irreversible actions"). Blocks (DB-poll) until a pending
    ApprovalRequest is resolved via `resolve()` — called by the dashboard's
    POST /approvals/{id}/decision route — or times out.

    The DB-poll loop is a deliberate, documented simplification: it avoids
    needing an event-loop-aware condition variable across the FastAPI
    process/thread boundary. "Boring" over clever, per Engineering
    Standards.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        event_logger: EventLogger,
        timeout_seconds: int = 3600,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._session_factory = session_factory
        self._event_logger = event_logger
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def request_and_wait(self, task_id: str, tool: Tool, args: dict[str, Any]) -> ApprovalDecision:
        approval_id = self._create_request(task_id, tool, args)

        self._event_logger.log(
            event_type="approval_requested",
            task_id=task_id,
            tool_name=tool.name,
            payload={"approval_id": approval_id, "args": args},
        )

        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            status = self._read_status(approval_id)
            if status != ApprovalStatus.PENDING:
                return self._finalize_decision(task_id, tool, approval_id, status)
            time.sleep(self.poll_interval_seconds)

        self._mark_timed_out(approval_id)
        self._event_logger.log(
            event_type="approval_resolved",
            task_id=task_id,
            tool_name=tool.name,
            payload={"approval_id": approval_id, "status": ApprovalStatus.TIMED_OUT.value},
        )
        return ApprovalDecision(approved=False, status=ApprovalStatus.TIMED_OUT, note="timed out")

    def resolve(self, approval_id: str, approved: bool, note: str | None, resolved_by: str) -> None:
        session = self._session_factory()
        try:
            approval = session.get(ApprovalRequest, approval_id)
            if approval is None:
                raise KeyError(f"unknown approval request: {approval_id!r}")
            if approval.status != ApprovalStatus.PENDING:
                raise ValueError(f"approval request already resolved: {approval.status.value}")

            approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
            approval.resolved_at = datetime.now(timezone.utc)
            approval.resolved_by = resolved_by
            approval.decision_note = note
            session.commit()
        finally:
            session.close()

    def _create_request(self, task_id: str, tool: Tool, args: dict[str, Any]) -> str:
        session = self._session_factory()
        try:
            approval = ApprovalRequest(
                task_id=task_id,
                tool_name=tool.name,
                risk_level=tool.risk_level,
                request_payload_json=json.dumps(args),
            )
            session.add(approval)

            task = session.get(Task, task_id)
            task.status = TaskStatus.AWAITING_APPROVAL
            session.commit()
            return approval.id
        finally:
            session.close()

    def _read_status(self, approval_id: str) -> ApprovalStatus:
        session = self._session_factory()
        try:
            approval = session.get(ApprovalRequest, approval_id)
            return approval.status
        finally:
            session.close()

    def _finalize_decision(self, task_id: str, tool: Tool, approval_id: str, status: ApprovalStatus) -> ApprovalDecision:
        session = self._session_factory()
        try:
            approval = session.get(ApprovalRequest, approval_id)
            note = approval.decision_note
        finally:
            session.close()

        self._event_logger.log(
            event_type="approval_resolved",
            task_id=task_id,
            tool_name=tool.name,
            payload={"approval_id": approval_id, "status": status.value},
        )
        return ApprovalDecision(approved=status == ApprovalStatus.APPROVED, status=status, note=note)

    def _mark_timed_out(self, approval_id: str) -> None:
        session = self._session_factory()
        try:
            approval = session.get(ApprovalRequest, approval_id)
            approval.status = ApprovalStatus.TIMED_OUT
            approval.resolved_at = datetime.now(timezone.utc)
            session.commit()
        finally:
            session.close()
