from __future__ import annotations

import json

from megachud.curiosity.engine import CuriosityHandler
from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.memory.store import MemoryStore
from megachud.models.curiosity import PendingQuestion, ResearchObjective
from megachud.models.evaluation import Evaluation
from megachud.models.reflection import Reflection
from megachud.models.task import Task, TaskStatus

VECTOR_DIM = 128


def build_handler(session_factory, threshold=0.35) -> CuriosityHandler:
    return CuriosityHandler(session_factory, vector_dim=VECTOR_DIM, similarity_threshold=threshold, research_objective_top_k=3)


def create_task_with_reflection(session_factory, prompt: str, become_long_term_knowledge: bool) -> str:
    session = session_factory()
    try:
        task = Task(title=prompt[:30], prompt=prompt, status=TaskStatus.SUCCEEDED)
        session.add(task)
        session.commit()
        task_id = task.id

        reflection = Reflection(
            task_id=task_id,
            what_worked="[]",
            what_failed='["something failed"]',
            wrong_assumptions='["assumed X"]',
            should_change='["do Y instead"]',
            become_long_term_knowledge=become_long_term_knowledge,
        )
        session.add(reflection)
        session.commit()
        return task_id
    finally:
        session.close()


def test_no_op_when_not_long_term_knowledge(session_factory):
    handler = build_handler(session_factory)
    task_id = create_task_with_reflection(session_factory, "a routine task", become_long_term_knowledge=False)

    logger = EventLogger(session_factory, EventBus(), on_event=handler)
    logger.log(event_type="task_completed", task_id=task_id, payload={})

    session = session_factory()
    try:
        assert session.query(PendingQuestion).count() == 0
        assert session.query(ResearchObjective).count() == 0
    finally:
        session.close()


def test_raises_question_and_objectives_when_no_prior_memory_exists(session_factory):
    handler = build_handler(session_factory)
    task_id = create_task_with_reflection(session_factory, "an unprecedented novel task", become_long_term_knowledge=True)

    logger = EventLogger(session_factory, EventBus(), on_event=handler)
    logger.log(event_type="task_completed", task_id=task_id, payload={})

    session = session_factory()
    try:
        questions = session.query(PendingQuestion).filter_by(source_task_id=task_id).all()
        objectives = session.query(ResearchObjective).filter_by(source_task_id=task_id).all()
        assert len(questions) == 1
        assert questions[0].status.value == "pending"
        assert {o.objective_type for o in objectives} == {"search_memory", "inspect_previous_work"}
    finally:
        session.close()


def test_no_op_when_similar_semantic_memory_already_exists(session_factory):
    store = MemoryStore(session_factory, vector_dim=VECTOR_DIM)
    # A pre-existing semantic memory from a DIFFERENT task, lexically close
    # to the new task's prompt.
    store.create_user_entry(content="deploying a web service requires configuring environment variables", title="prior lesson")
    # create_user_entry makes a USER entry; force it to SEMANTIC directly so
    # the curiosity check (which searches SEMANTIC only) can find it.
    session = session_factory()
    try:
        from megachud.models.memory_entry import MemoryEntry, MemoryType

        entry = session.query(MemoryEntry).order_by(MemoryEntry.created_at.desc()).first()
        entry.memory_type = MemoryType.SEMANTIC
        session.commit()
    finally:
        session.close()

    handler = build_handler(session_factory, threshold=0.05)  # low threshold, easy to clear
    task_id = create_task_with_reflection(
        session_factory, "deploying a web service requires configuring environment variables", become_long_term_knowledge=True
    )

    logger = EventLogger(session_factory, EventBus(), on_event=handler)
    logger.log(event_type="task_completed", task_id=task_id, payload={})

    session = session_factory()
    try:
        assert session.query(PendingQuestion).filter_by(source_task_id=task_id).count() == 0
    finally:
        session.close()


def test_self_match_does_not_suppress_curiosity(session_factory):
    """The critical fix: TaskCompletionHandler creates a semantic entry
    FROM this exact task (source_task_id == task_id) moments before
    CuriosityHandler runs — that self-authored entry must not count as a
    "close precedent," or curiosity would silently never fire again after
    the first become_long_term_knowledge case.
    """
    handler = build_handler(session_factory, threshold=0.35)
    task_id = create_task_with_reflection(session_factory, "a genuinely novel situation", become_long_term_knowledge=True)

    # Simulate what TaskCompletionHandler already did moments earlier: a
    # semantic MemoryEntry authored FROM this same task, with content
    # highly similar to the task prompt itself.
    store = MemoryStore(session_factory, vector_dim=VECTOR_DIM)
    session = session_factory()
    try:
        task = session.get(Task, task_id)
    finally:
        session.close()

    from megachud.models.memory_entry import MemoryEntry, MemoryType

    session = session_factory()
    try:
        self_entry = MemoryEntry(
            memory_type=MemoryType.SEMANTIC,
            title="self lesson",
            content=task.prompt,  # maximally similar to itself
            source_task_id=task_id,
            embedding_json=json.dumps([0.0] * VECTOR_DIM),
        )
        session.add(self_entry)
        session.commit()
    finally:
        session.close()

    from megachud.memory.vectorizer import embed

    session = session_factory()
    try:
        entry = session.get(MemoryEntry, self_entry.id)
        entry.embedding_json = json.dumps(embed(task.prompt, VECTOR_DIM))
        session.commit()
    finally:
        session.close()

    logger = EventLogger(session_factory, EventBus(), on_event=handler)
    logger.log(event_type="task_completed", task_id=task_id, payload={})

    session = session_factory()
    try:
        # Despite a "perfect match" existing, it's self-authored and must
        # be excluded — curiosity should still fire.
        assert session.query(PendingQuestion).filter_by(source_task_id=task_id).count() == 1
    finally:
        session.close()


def test_reflect_without_task_id_is_noop(session_factory):
    handler = build_handler(session_factory)
    logger = EventLogger(session_factory, EventBus(), on_event=handler)
    logger.log(event_type="task_completed", task_id=None, payload={})  # should not raise
