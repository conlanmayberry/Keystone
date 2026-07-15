from __future__ import annotations

import json

from megachud.memory.store import MemoryStore
from megachud.models.memory_entry import MemoryType
from megachud.models.reflection import Reflection
from megachud.models.task import Task


def make_store(session_factory) -> MemoryStore:
    return MemoryStore(session_factory, vector_dim=64)


def create_task(session_factory) -> Task:
    session = session_factory()
    try:
        task = Task(title="t", prompt="do the thing")
        session.add(task)
        session.commit()
        session.refresh(task)
        session.expunge(task)
        return task
    finally:
        session.close()


def create_reflection(session_factory, task_id, become_long_term_knowledge) -> Reflection:
    session = session_factory()
    try:
        reflection = Reflection(
            task_id=task_id,
            what_worked='["it worked"]',
            what_failed="[]",
            wrong_assumptions='["assumed X"]' if become_long_term_knowledge else "[]",
            should_change='["change Y"]',
            become_long_term_knowledge=become_long_term_knowledge,
        )
        session.add(reflection)
        session.commit()
        session.refresh(reflection)
        session.expunge(reflection)
        return reflection
    finally:
        session.close()


def test_episodic_only_when_not_long_term(session_factory):
    store = make_store(session_factory)
    task = create_task(session_factory)
    reflection = create_reflection(session_factory, task.id, become_long_term_knowledge=False)

    entries = store.create_episodic_from_reflection(task, reflection)

    assert len(entries) == 1
    assert entries[0].memory_type == MemoryType.EPISODIC
    assert entries[0].source_task_id == task.id
    assert json.loads(entries[0].embedding_json)


def test_episodic_and_semantic_when_long_term(session_factory):
    store = make_store(session_factory)
    task = create_task(session_factory)
    reflection = create_reflection(session_factory, task.id, become_long_term_knowledge=True)

    entries = store.create_episodic_from_reflection(task, reflection)

    types = {e.memory_type for e in entries}
    assert types == {MemoryType.EPISODIC, MemoryType.SEMANTIC}


def test_create_user_entry(session_factory):
    store = make_store(session_factory)
    entry = store.create_user_entry(content="I prefer terse commit messages", title="commit style", tags=["prefs"])

    assert entry.memory_type == MemoryType.USER
    assert entry.source_task_id is None
    assert json.loads(entry.tags_json) == ["prefs"]


def test_list_by_type_filters(session_factory):
    store = make_store(session_factory)
    store.create_user_entry(content="fact one", title="fact one")
    store.create_user_entry(content="fact two", title="fact two")
    task = create_task(session_factory)
    reflection = create_reflection(session_factory, task.id, become_long_term_knowledge=False)
    store.create_episodic_from_reflection(task, reflection)

    user_entries = store.list_by_type(MemoryType.USER)
    episodic_entries = store.list_by_type(MemoryType.EPISODIC)

    assert len(user_entries) == 2
    assert len(episodic_entries) == 1


def test_get_and_set_vault_path(session_factory):
    store = make_store(session_factory)
    entry = store.create_user_entry(content="x", title="x")

    assert store.get(entry.id) is not None
    assert store.get("does-not-exist") is None

    store.set_vault_path(entry.id, "user/abc.md")
    fetched = store.get(entry.id)
    assert fetched.vault_path == "user/abc.md"
