from __future__ import annotations

from megachud.memory.retrieval import search
from megachud.memory.store import MemoryStore
from megachud.models.memory_entry import MemoryType

VECTOR_DIM = 128


def make_store(session_factory) -> MemoryStore:
    return MemoryStore(session_factory, vector_dim=VECTOR_DIM)


def test_search_ranks_similar_content_top(session_factory):
    store = make_store(session_factory)
    store.create_user_entry(content="the quick brown fox jumps over the lazy dog", title="fox")
    store.create_user_entry(content="quantum mechanics and general relativity", title="physics")
    store.create_user_entry(content="a completely unrelated grocery list of apples and bread", title="groceries")

    results = search(session_factory, "brown fox jumping over a dog", VECTOR_DIM, top_k=3)

    assert results[0].entry.title == "fox"
    assert results[0].score >= results[1].score >= results[2].score


def test_search_respects_top_k(session_factory):
    store = make_store(session_factory)
    for i in range(5):
        store.create_user_entry(content=f"entry number {i} about topic {i}", title=f"entry {i}")

    results = search(session_factory, "topic", VECTOR_DIM, top_k=2)
    assert len(results) == 2


def test_search_filters_by_memory_type(session_factory):
    store = make_store(session_factory)
    store.create_user_entry(content="user fact about preferences", title="user fact")

    results = search(session_factory, "preferences", VECTOR_DIM, memory_type=MemoryType.EPISODIC, top_k=5)
    assert results == []

    results = search(session_factory, "preferences", VECTOR_DIM, memory_type=MemoryType.USER, top_k=5)
    assert len(results) == 1


def test_search_updates_access_tracking(session_factory):
    store = make_store(session_factory)
    entry = store.create_user_entry(content="track my access", title="tracked")
    assert entry.access_count == 0
    assert entry.last_accessed_at is None

    search(session_factory, "track my access", VECTOR_DIM, top_k=1)

    updated = store.get(entry.id)
    assert updated.access_count == 1
    assert updated.last_accessed_at is not None


def test_search_on_empty_store_returns_empty_list(session_factory):
    results = search(session_factory, "anything", VECTOR_DIM, top_k=5)
    assert results == []
