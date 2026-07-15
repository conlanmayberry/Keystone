from __future__ import annotations

from megachud.models.evaluation import Evaluation
from megachud.models.memory_entry import MemoryEntry, MemoryType
from megachud.models.reflection import Reflection
from megachud.models.task import Task


def test_memory_entry_roundtrip(db_session):
    task = Task(title="t", prompt="p")
    db_session.add(task)
    db_session.commit()

    entry = MemoryEntry(
        memory_type=MemoryType.EPISODIC,
        title="episode",
        content="did a thing",
        source_task_id=task.id,
        tags_json='["tag1"]',
        embedding_json="[0.1, 0.2]",
    )
    db_session.add(entry)
    db_session.commit()

    fetched = db_session.get(MemoryEntry, entry.id)
    assert fetched.memory_type == MemoryType.EPISODIC
    assert fetched.source_task_id == task.id
    assert fetched.importance == 0.5
    assert fetched.access_count == 0
    assert fetched.vault_path is None
    assert fetched.created_at is not None


def test_reflection_roundtrip(db_session):
    task = Task(title="t", prompt="p")
    db_session.add(task)
    db_session.commit()

    evaluation = Evaluation(task_id=task.id, success=True, checks_json="[]")
    db_session.add(evaluation)
    db_session.commit()

    reflection = Reflection(
        task_id=task.id,
        evaluation_id=evaluation.id,
        what_worked='["all checks passed"]',
        what_failed="[]",
        wrong_assumptions="[]",
        should_change='["no change indicated"]',
        become_long_term_knowledge=False,
    )
    db_session.add(reflection)
    db_session.commit()

    fetched = db_session.get(Reflection, reflection.id)
    assert fetched.task_id == task.id
    assert fetched.evaluation_id == evaluation.id
    assert fetched.become_long_term_knowledge is False
    assert fetched.generator == "deterministic_v1"


def test_reflection_without_evaluation(db_session):
    task = Task(title="t", prompt="p")
    db_session.add(task)
    db_session.commit()

    reflection = Reflection(task_id=task.id, evaluation_id=None, become_long_term_knowledge=True)
    db_session.add(reflection)
    db_session.commit()

    fetched = db_session.get(Reflection, reflection.id)
    assert fetched.evaluation_id is None
    assert fetched.become_long_term_knowledge is True


def test_memory_entry_links_to_reflection(db_session):
    task = Task(title="t", prompt="p")
    db_session.add(task)
    db_session.commit()

    reflection = Reflection(task_id=task.id)
    db_session.add(reflection)
    db_session.commit()

    entry = MemoryEntry(
        memory_type=MemoryType.SEMANTIC,
        title="lesson",
        content="generalized lesson",
        source_task_id=task.id,
        reflection_id=reflection.id,
    )
    db_session.add(entry)
    db_session.commit()

    fetched = db_session.get(MemoryEntry, entry.id)
    assert fetched.reflection_id == reflection.id
