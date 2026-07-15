from __future__ import annotations

import json

from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.memory.store import MemoryStore
from megachud.models.evaluation import Evaluation
from megachud.models.memory_entry import MemoryEntry, MemoryType
from megachud.models.reflection import Reflection
from megachud.models.task import Task, TaskStatus
from megachud.obsidian.vault import VaultWriter
from megachud.reflection.engine import ReflectionEngine
from megachud.reflection.handler import TaskCompletionHandler

VECTOR_DIM = 64


def build_handler(session_factory, tmp_vault) -> TaskCompletionHandler:
    reflection_engine = ReflectionEngine(session_factory)
    memory_store = MemoryStore(session_factory, vector_dim=VECTOR_DIM)
    vault_writer = VaultWriter(tmp_vault)
    return TaskCompletionHandler(reflection_engine, memory_store, vault_writer)


def create_succeeded_task(session_factory) -> str:
    session = session_factory()
    try:
        task = Task(title="write hello.txt", prompt="write a file", status=TaskStatus.SUCCEEDED, retry_count=0)
        session.add(task)
        session.commit()
        task_id = task.id

        evaluation = Evaluation(
            task_id=task_id,
            success=True,
            checks_json=json.dumps([{"name": "tool_calls_succeeded", "passed": True, "detail": "all ok"}]),
        )
        session.add(evaluation)
        session.commit()
        return task_id
    finally:
        session.close()


def test_task_completed_event_triggers_full_pipeline(session_factory, tmp_vault):
    handler = build_handler(session_factory, tmp_vault)
    task_id = create_succeeded_task(session_factory)

    logger = EventLogger(session_factory, EventBus(), on_event=handler)
    logger.log(event_type="task_completed", task_id=task_id, payload={})

    session = session_factory()
    try:
        reflections = session.query(Reflection).filter_by(task_id=task_id).all()
        assert len(reflections) == 1

        entries = session.query(MemoryEntry).filter_by(source_task_id=task_id).all()
        assert len(entries) == 1
        assert entries[0].memory_type == MemoryType.EPISODIC
        assert entries[0].vault_path is not None
        entry_vault_path = entries[0].vault_path
    finally:
        session.close()

    task_note = tmp_vault / "tasks" / f"{task_id}.md"
    assert task_note.exists()
    assert f"[[episodic/{entries[0].id}]]" in task_note.read_text(encoding="utf-8")

    entry_note = tmp_vault / entry_vault_path
    assert entry_note.exists()
    assert f"[[tasks/{task_id}" in entry_note.read_text(encoding="utf-8")


def test_non_completion_events_do_not_trigger_pipeline(session_factory, tmp_vault):
    handler = build_handler(session_factory, tmp_vault)
    task_id = create_succeeded_task(session_factory)

    logger = EventLogger(session_factory, EventBus(), on_event=handler)
    logger.log(event_type="tool_call", task_id=task_id, tool_name="write_file", payload={})

    session = session_factory()
    try:
        assert session.query(Reflection).filter_by(task_id=task_id).count() == 0
    finally:
        session.close()


def test_handler_ignores_events_without_task_id(session_factory, tmp_vault):
    handler = build_handler(session_factory, tmp_vault)

    logger = EventLogger(session_factory, EventBus(), on_event=handler)
    # Should not raise even though there's no task to reflect on.
    logger.log(event_type="task_completed", task_id=None, payload={})


def test_failed_task_without_evaluation_still_produces_reflection(session_factory, tmp_vault):
    handler = build_handler(session_factory, tmp_vault)

    session = session_factory()
    try:
        task = Task(title="denied task", prompt="p", status=TaskStatus.FAILED, result_summary="approval not granted for x")
        session.add(task)
        session.commit()
        task_id = task.id
    finally:
        session.close()

    logger = EventLogger(session_factory, EventBus(), on_event=handler)
    logger.log(event_type="task_failed", task_id=task_id, payload={"reason": "approval_denied"})

    session = session_factory()
    try:
        reflection = session.query(Reflection).filter_by(task_id=task_id).one()
        assert reflection.evaluation_id is None
        assert reflection.become_long_term_knowledge is True

        entries = session.query(MemoryEntry).filter_by(source_task_id=task_id).all()
        # A failure with wrong_assumptions is "long term knowledge" -> both episodic + semantic
        assert {e.memory_type for e in entries} == {MemoryType.EPISODIC, MemoryType.SEMANTIC}
    finally:
        session.close()
