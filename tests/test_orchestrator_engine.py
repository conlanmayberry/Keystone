from __future__ import annotations

import json
import threading
import time

from megachud.evaluation.engine import EvaluationEngine
from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.approval import ApprovalRequest
from megachud.models.task import Task, TaskStatus
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.orchestrator.engine import Orchestrator
from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry
from tests.fixtures.dummy_tools import DummyIrreversibleTool


def make_orchestrator(session_factory, tmp_workspace, extra_tools=(), approval_timeout=2, approval_poll=0.05):
    bus = EventBus()
    event_logger = EventLogger(session_factory, bus)

    registry = ToolRegistry()
    registry.register(ReadFileTool(tmp_workspace))
    registry.register(WriteFileTool(tmp_workspace))
    for tool in extra_tools:
        registry.register(tool)

    approval_gate = ApprovalGate(
        session_factory, event_logger, timeout_seconds=approval_timeout, poll_interval_seconds=approval_poll
    )
    orchestrator = Orchestrator(
        session_factory=session_factory,
        tool_registry=registry,
        approval_gate=approval_gate,
        evaluator=EvaluationEngine(),
        event_logger=event_logger,
        workspace_root=tmp_workspace,
    )
    return orchestrator, approval_gate


def create_task(session_factory, plan, execution_mode=None) -> str:
    session = session_factory()
    try:
        task = Task(title="t", prompt="p", plan_json=json.dumps(plan), execution_mode=execution_mode)
        session.add(task)
        session.commit()
        return task.id
    finally:
        session.close()


def test_happy_path_marks_task_succeeded(session_factory, tmp_workspace):
    orchestrator, _ = make_orchestrator(session_factory, tmp_workspace)
    plan = [
        {"tool_name": "write_file", "args": {"path": "a.txt", "content": "hi"}},
        {"tool_name": "read_file", "args": {"path": "a.txt"}},
    ]
    task_id = create_task(session_factory, plan)

    result = orchestrator.run_task(task_id)

    assert result.status == TaskStatus.SUCCEEDED
    assert result.completed_at is not None


def test_tool_failure_marks_task_failed(session_factory, tmp_workspace):
    orchestrator, _ = make_orchestrator(session_factory, tmp_workspace)
    plan = [{"tool_name": "read_file", "args": {"path": "does_not_exist.txt"}}]
    task_id = create_task(session_factory, plan)

    result = orchestrator.run_task(task_id)

    assert result.status == TaskStatus.FAILED
    assert "read_file" in result.result_summary


def test_high_risk_tool_blocks_until_approved_then_succeeds(session_factory, tmp_workspace):
    orchestrator, gate = make_orchestrator(session_factory, tmp_workspace, extra_tools=[DummyIrreversibleTool()])
    plan = [{"tool_name": "dummy_irreversible", "args": {}}]
    task_id = create_task(session_factory, plan)

    def approve_soon():
        time.sleep(0.15)
        session = session_factory()
        try:
            approval = session.query(ApprovalRequest).filter_by(task_id=task_id).one()
            approval_id = approval.id
        finally:
            session.close()
        gate.resolve(approval_id, approved=True, note="approved in test", resolved_by="tester")

    thread = threading.Thread(target=approve_soon)
    thread.start()
    result = orchestrator.run_task(task_id)
    thread.join()

    assert result.status == TaskStatus.SUCCEEDED


def test_full_manual_mode_gates_even_a_low_risk_tool(session_factory, tmp_workspace):
    # ReadFileTool is RiskLevel.LOW — never gated in "auto" mode. Proves
    # full_manual's gating condition fires regardless of risk_level, not
    # just for HIGH_IRREVERSIBLE tools, using no new dummy fixture.
    (tmp_workspace / "a.txt").write_text("hi", encoding="utf-8")
    orchestrator, gate = make_orchestrator(session_factory, tmp_workspace)
    plan = [{"tool_name": "read_file", "args": {"path": "a.txt"}}]
    task_id = create_task(session_factory, plan, execution_mode="full_manual")

    def approve_soon():
        time.sleep(0.15)
        session = session_factory()
        try:
            approval = session.query(ApprovalRequest).filter_by(task_id=task_id).one()
            approval_id = approval.id
        finally:
            session.close()
        gate.resolve(approval_id, approved=True, note="approved in test", resolved_by="tester")

    thread = threading.Thread(target=approve_soon)
    thread.start()
    result = orchestrator.run_task(task_id)
    thread.join()

    assert result.status == TaskStatus.SUCCEEDED


def test_full_manual_mode_denied_step_fails_task(session_factory, tmp_workspace):
    (tmp_workspace / "a.txt").write_text("hi", encoding="utf-8")
    orchestrator, gate = make_orchestrator(session_factory, tmp_workspace)
    plan = [{"tool_name": "read_file", "args": {"path": "a.txt"}}]
    task_id = create_task(session_factory, plan, execution_mode="full_manual")

    def deny_soon():
        time.sleep(0.15)
        session = session_factory()
        try:
            approval = session.query(ApprovalRequest).filter_by(task_id=task_id).one()
            approval_id = approval.id
        finally:
            session.close()
        gate.resolve(approval_id, approved=False, note="denied in test", resolved_by="tester")

    thread = threading.Thread(target=deny_soon)
    thread.start()
    result = orchestrator.run_task(task_id)
    thread.join()

    assert result.status == TaskStatus.FAILED


def test_auto_mode_does_not_gate_a_low_risk_tool(session_factory, tmp_workspace):
    (tmp_workspace / "a.txt").write_text("hi", encoding="utf-8")
    orchestrator, _ = make_orchestrator(session_factory, tmp_workspace)
    plan = [{"tool_name": "read_file", "args": {"path": "a.txt"}}]
    task_id = create_task(session_factory, plan, execution_mode="auto")

    result = orchestrator.run_task(task_id)  # no approval thread — must not block

    assert result.status == TaskStatus.SUCCEEDED


def test_high_risk_tool_denied_marks_task_failed(session_factory, tmp_workspace):
    orchestrator, gate = make_orchestrator(session_factory, tmp_workspace, extra_tools=[DummyIrreversibleTool()])
    plan = [{"tool_name": "dummy_irreversible", "args": {}}]
    task_id = create_task(session_factory, plan)

    def deny_soon():
        time.sleep(0.15)
        session = session_factory()
        try:
            approval = session.query(ApprovalRequest).filter_by(task_id=task_id).one()
            approval_id = approval.id
        finally:
            session.close()
        gate.resolve(approval_id, approved=False, note="denied in test", resolved_by="tester")

    thread = threading.Thread(target=deny_soon)
    thread.start()
    result = orchestrator.run_task(task_id)
    thread.join()

    assert result.status == TaskStatus.FAILED
    assert "dummy_irreversible" in result.result_summary
