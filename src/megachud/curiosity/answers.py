from __future__ import annotations

from datetime import datetime, timezone

from megachud.memory.store import MemoryStore
from megachud.models.curiosity import PendingQuestion, QuestionStatus
from megachud.models.memory_entry import MemoryEntry
from megachud.obsidian.vault import VaultWriter


def answer_question(
    session_factory,
    memory_store: MemoryStore,
    vault_writer: VaultWriter,
    question_id: str,
    answer_text: str,
) -> MemoryEntry:
    """Marks the PendingQuestion ANSWERED, then reuses
    MemoryStore.create_user_entry + VaultWriter.write_memory_entry — the
    exact sequence routes_memory.create_user_memory already performs —
    rather than reimplementing the memory-write sequence. Links back via
    answered_memory_entry_id.
    """
    session = session_factory()
    try:
        question = session.get(PendingQuestion, question_id)
        if question is None:
            raise KeyError(f"unknown question: {question_id!r}")
        if question.status != QuestionStatus.PENDING:
            raise ValueError(f"question already resolved: {question.status.value}")

        question.answer = answer_text
        question.status = QuestionStatus.ANSWERED
        question.resolved_at = datetime.now(timezone.utc)
        session.commit()
        question_text = question.question
    finally:
        session.close()

    entry = memory_store.create_user_entry(
        content=answer_text,
        title=f"Answer: {question_text[:80]}",
        tags=["curiosity_answer"],
    )
    relative_path = vault_writer.write_memory_entry(entry, None)
    memory_store.set_vault_path(entry.id, str(relative_path))

    session = session_factory()
    try:
        question = session.get(PendingQuestion, question_id)
        question.answered_memory_entry_id = entry.id
        session.commit()
    finally:
        session.close()

    return memory_store.get(entry.id)
