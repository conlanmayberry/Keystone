from __future__ import annotations

from megachud.models.approval import ApprovalRequest, ApprovalStatus, RiskLevel
from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.task import Task, TaskStatus


def test_task_roundtrip(db_session):
    task = Task(title="write a file", prompt="write hello.txt", plan_json="[]")
    db_session.add(task)
    db_session.commit()

    fetched = db_session.get(Task, task.id)
    assert fetched is not None
    assert fetched.title == "write a file"
    assert fetched.status == TaskStatus.PENDING
    assert fetched.created_at is not None


def test_event_roundtrip_with_task(db_session):
    task = Task(title="t", prompt="p")
    db_session.add(task)
    db_session.commit()

    event = Event(task_id=task.id, event_type="task_started", payload_json="{}")
    db_session.add(event)
    db_session.commit()

    fetched = db_session.get(Event, event.id)
    assert fetched.task_id == task.id
    assert fetched.event_type == "task_started"
    assert fetched.cost_usd is None
    assert fetched.reflection is None


def test_evaluation_roundtrip(db_session):
    task = Task(title="t", prompt="p")
    db_session.add(task)
    db_session.commit()

    evaluation = Evaluation(task_id=task.id, success=True, checks_json="[]")
    db_session.add(evaluation)
    db_session.commit()

    fetched = db_session.get(Evaluation, evaluation.id)
    assert fetched.success is True


def test_approval_request_roundtrip(db_session):
    task = Task(title="t", prompt="p")
    db_session.add(task)
    db_session.commit()

    approval = ApprovalRequest(
        task_id=task.id,
        tool_name="dummy_irreversible",
        risk_level=RiskLevel.HIGH_IRREVERSIBLE,
        request_payload_json="{}",
    )
    db_session.add(approval)
    db_session.commit()

    fetched = db_session.get(ApprovalRequest, approval.id)
    assert fetched.status == ApprovalStatus.PENDING
    assert fetched.risk_level == RiskLevel.HIGH_IRREVERSIBLE
