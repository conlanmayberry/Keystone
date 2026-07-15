from __future__ import annotations

import json

from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.task import Task, TaskStatus
from megachud.reflection.engine import ReflectionEngine


def test_reflect_persists_and_returns_reflection(session_factory):
    session = session_factory()
    try:
        task = Task(title="t", prompt="p", status=TaskStatus.SUCCEEDED, retry_count=0)
        session.add(task)
        session.commit()
        task_id = task.id

        evaluation = Evaluation(
            task_id=task_id,
            success=True,
            checks_json=json.dumps([{"name": "tool_calls_succeeded", "passed": True, "detail": "ok"}]),
        )
        session.add(evaluation)
        session.commit()
    finally:
        session.close()

    engine = ReflectionEngine(session_factory)
    task, reflection = engine.reflect(task_id)

    assert reflection.id is not None
    assert reflection.task_id == task_id
    assert reflection.evaluation_id is not None
    assert json.loads(reflection.what_failed) == []
    assert reflection.become_long_term_knowledge is False

    # persisted, independently re-queryable
    session = session_factory()
    try:
        fetched = session.query(Evaluation).filter_by(task_id=task_id).count()
        assert fetched == 1
    finally:
        session.close()


def test_reflect_handles_task_with_no_evaluation(session_factory):
    session = session_factory()
    try:
        task = Task(title="t", prompt="p", status=TaskStatus.FAILED, result_summary="approval not granted for x")
        session.add(task)
        session.commit()
        task_id = task.id

        event = Event(
            task_id=task_id,
            event_type="approval_resolved",
            payload_json=json.dumps({"status": "denied"}),
        )
        session.add(event)
        session.commit()
    finally:
        session.close()

    engine = ReflectionEngine(session_factory)
    _, reflection = engine.reflect(task_id)

    assert reflection.evaluation_id is None
    assert reflection.become_long_term_knowledge is True
    assert "approval not granted for x" in json.loads(reflection.what_failed)
