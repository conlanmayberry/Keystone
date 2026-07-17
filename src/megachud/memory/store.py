from __future__ import annotations

import json

from sqlalchemy.orm import Session, sessionmaker

from megachud.memory.vectorizer import embed
from megachud.models.memory_entry import MemoryEntry, MemoryType
from megachud.models.reflection import Reflection
from megachud.models.task import Task


class MemoryStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        vector_dim: int,
        agent_id: str | None = None,
        project_name: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._vector_dim = vector_dim
        self._agent_id = agent_id
        self._project_name = project_name

    def create_episodic_from_reflection(self, task: Task, reflection: Reflection) -> list[MemoryEntry]:
        """Always creates one EPISODIC entry. If reflection.become_long_term_knowledge,
        also creates one SEMANTIC entry — the concrete answer to the spec's
        "should this become long-term knowledge?" question.
        """
        created = [
            self._create_entry(
                memory_type=MemoryType.EPISODIC,
                title=task.title,
                content=self._render_episodic_content(task, reflection),
                source_task_id=task.id,
                reflection_id=reflection.id,
                tags=["episodic"],
            )
        ]

        if reflection.become_long_term_knowledge:
            created.append(
                self._create_entry(
                    memory_type=MemoryType.SEMANTIC,
                    title=f"Lesson from: {task.title}",
                    content=self._render_semantic_content(reflection),
                    source_task_id=task.id,
                    reflection_id=reflection.id,
                    tags=["lesson"],
                )
            )

        return created

    def create_user_entry(self, content: str, title: str, tags: list[str] | None = None) -> MemoryEntry:
        """The only way USER memory gets populated this round — human-entered
        via API/dashboard. No LLM extraction exists yet in this project.
        """
        return self._create_entry(
            memory_type=MemoryType.USER,
            title=title,
            content=content,
            source_task_id=None,
            reflection_id=None,
            tags=tags or [],
        )

    def list_by_type(self, memory_type: MemoryType, limit: int = 50) -> list[MemoryEntry]:
        session = self._session_factory()
        try:
            entries = (
                session.query(MemoryEntry)
                .filter_by(memory_type=memory_type)
                .order_by(MemoryEntry.created_at.desc())
                .limit(limit)
                .all()
            )
            for entry in entries:
                session.expunge(entry)
            return entries
        finally:
            session.close()

    def get(self, entry_id: str) -> MemoryEntry | None:
        session = self._session_factory()
        try:
            entry = session.get(MemoryEntry, entry_id)
            if entry is not None:
                session.expunge(entry)
            return entry
        finally:
            session.close()

    def set_vault_path(self, entry_id: str, path: str) -> None:
        session = self._session_factory()
        try:
            entry = session.get(MemoryEntry, entry_id)
            entry.vault_path = path
            session.commit()
        finally:
            session.close()

    def _create_entry(
        self,
        *,
        memory_type: MemoryType,
        title: str,
        content: str,
        source_task_id: str | None,
        reflection_id: int | None,
        tags: list[str],
    ) -> MemoryEntry:
        embedding = embed(content, self._vector_dim)
        session = self._session_factory()
        try:
            entry = MemoryEntry(
                memory_type=memory_type,
                title=title,
                content=content,
                source_task_id=source_task_id,
                reflection_id=reflection_id,
                tags_json=json.dumps(tags),
                embedding_json=json.dumps(embedding),
                agent_id=self._agent_id,
                project_name=self._project_name,
            )
            session.add(entry)
            session.commit()
            session.refresh(entry)
            session.expunge(entry)
            return entry
        finally:
            session.close()

    def _render_episodic_content(self, task: Task, reflection: Reflection) -> str:
        parts = [task.prompt, *json.loads(reflection.what_worked), *json.loads(reflection.what_failed)]
        return "\n".join(parts)

    def _render_semantic_content(self, reflection: Reflection) -> str:
        parts = [*json.loads(reflection.should_change), *json.loads(reflection.wrong_assumptions)]
        return "\n".join(parts)
