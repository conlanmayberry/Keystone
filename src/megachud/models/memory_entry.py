from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin, UUIDPKMixin


class MemoryType(str, enum.Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    USER = "user"


class MemoryEntry(UUIDPKMixin, CreatedAtMixin, Base):
    __tablename__ = "memory_entries"

    memory_type: Mapped[MemoryType] = mapped_column(Enum(MemoryType), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    source_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    reflection_id: Mapped[int | None] = mapped_column(ForeignKey("reflections.id"), nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")

    # Aging/ranking inputs per spec's Memory System "aging" responsibility.
    # No background decay job exists yet — these are populated/used by
    # retrieval.search() now, so a later phase can add decay without a
    # migration.
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    # JSON list[float], fixed length == settings.memory.vector_dim.
    embedding_json: Mapped[str] = mapped_column(Text, default="[]")

    # Relative path under vault/, set once the vault writer has written this
    # entry's note.
    vault_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Phase 5 structural multi-agent/multi-project seam — see task.py's
    # matching columns for the full rationale.
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
