from __future__ import annotations

import threading
import time

from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.approval import ApprovalRequest, ApprovalStatus
from megachud.models.task import Task
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.tools.file_tools import WriteFileTool


def make_gate(session_factory, timeout=2, poll=0.05) -> ApprovalGate:
    logger = EventLogger(session_factory, EventBus())
    return ApprovalGate(session_factory, logger, timeout_seconds=timeout, poll_interval_seconds=poll)


def create_task(session_factory) -> str:
    session = session_factory()
    try:
        task = Task(title="t", prompt="p")
        session.add(task)
        session.commit()
        return task.id
    finally:
        session.close()


def _resolve_after_delay(session_factory, task_id, gate, approved, delay=0.15):
    def worker():
        time.sleep(delay)
        session = session_factory()
        try:
            approval = session.query(ApprovalRequest).filter_by(task_id=task_id).one()
            approval_id = approval.id
        finally:
            session.close()
        gate.resolve(approval_id, approved=approved, note="test decision", resolved_by="tester")

    thread = threading.Thread(target=worker)
    thread.start()
    return thread


def test_request_creates_row_and_awaits_resolution(session_factory, tmp_workspace):
    gate = make_gate(session_factory)
    task_id = create_task(session_factory)
    tool = WriteFileTool(tmp_workspace)

    thread = _resolve_after_delay(session_factory, task_id, gate, approved=True)
    decision = gate.request_and_wait(task_id, tool, {"path": "x.txt", "content": "y"})
    thread.join()

    assert decision.approved is True
    assert decision.status == ApprovalStatus.APPROVED
    assert decision.note == "test decision"


def test_denial_returns_not_approved(session_factory, tmp_workspace):
    gate = make_gate(session_factory)
    task_id = create_task(session_factory)
    tool = WriteFileTool(tmp_workspace)

    thread = _resolve_after_delay(session_factory, task_id, gate, approved=False)
    decision = gate.request_and_wait(task_id, tool, {})
    thread.join()

    assert decision.approved is False
    assert decision.status == ApprovalStatus.DENIED


def test_timeout_returns_without_hanging(session_factory, tmp_workspace):
    gate = make_gate(session_factory, timeout=1, poll=0.05)
    task_id = create_task(session_factory)
    tool = WriteFileTool(tmp_workspace)

    start = time.monotonic()
    decision = gate.request_and_wait(task_id, tool, {})
    elapsed = time.monotonic() - start

    assert decision.approved is False
    assert decision.status == ApprovalStatus.TIMED_OUT
    assert elapsed < 3


def test_resolving_already_resolved_request_raises(session_factory, tmp_workspace):
    gate = make_gate(session_factory)
    task_id = create_task(session_factory)
    tool = WriteFileTool(tmp_workspace)

    thread = _resolve_after_delay(session_factory, task_id, gate, approved=True)
    gate.request_and_wait(task_id, tool, {})
    thread.join()

    session = session_factory()
    try:
        approval = session.query(ApprovalRequest).filter_by(task_id=task_id).one()
        approval_id = approval.id
    finally:
        session.close()

    import pytest

    with pytest.raises(ValueError):
        gate.resolve(approval_id, approved=True, note=None, resolved_by="tester")
