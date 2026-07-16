from __future__ import annotations

import pytest

from megachud.curiosity.answers import answer_question
from megachud.memory.store import MemoryStore
from megachud.models.curiosity import PendingQuestion, QuestionStatus
from megachud.models.memory_entry import MemoryType
from megachud.obsidian.vault import VaultWriter

VECTOR_DIM = 64


def create_pending_question(session_factory, question_text="What should I do?") -> str:
    session = session_factory()
    try:
        question = PendingQuestion(question=question_text, context="test")
        session.add(question)
        session.commit()
        return question.id
    finally:
        session.close()


def test_answer_question_creates_user_memory_and_links_back(session_factory, tmp_vault):
    store = MemoryStore(session_factory, vector_dim=VECTOR_DIM)
    vault_writer = VaultWriter(tmp_vault)
    question_id = create_pending_question(session_factory, "How should retries be handled?")

    entry = answer_question(session_factory, store, vault_writer, question_id, "Cap retries at 3 with backoff.")

    assert entry.memory_type == MemoryType.USER
    assert "Cap retries at 3" in entry.content
    assert entry.vault_path is not None
    assert (tmp_vault / entry.vault_path).exists()

    session = session_factory()
    try:
        question = session.get(PendingQuestion, question_id)
        assert question.status == QuestionStatus.ANSWERED
        assert question.answer == "Cap retries at 3 with backoff."
        assert question.answered_memory_entry_id == entry.id
        assert question.resolved_at is not None
    finally:
        session.close()


def test_answer_question_raises_if_already_answered(session_factory, tmp_vault):
    store = MemoryStore(session_factory, vector_dim=VECTOR_DIM)
    vault_writer = VaultWriter(tmp_vault)
    question_id = create_pending_question(session_factory)

    answer_question(session_factory, store, vault_writer, question_id, "first answer")

    with pytest.raises(ValueError):
        answer_question(session_factory, store, vault_writer, question_id, "second answer")


def test_answer_question_raises_on_unknown_question(session_factory, tmp_vault):
    store = MemoryStore(session_factory, vector_dim=VECTOR_DIM)
    vault_writer = VaultWriter(tmp_vault)

    with pytest.raises(KeyError):
        answer_question(session_factory, store, vault_writer, "does-not-exist", "answer")
