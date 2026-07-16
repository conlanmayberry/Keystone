from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin, UUIDPKMixin


class QuestionStatus(str, enum.Enum):
    PENDING = "pending"
    ANSWERED = "answered"
    DISMISSED = "dismissed"


class PendingQuestion(UUIDPKMixin, CreatedAtMixin, Base):
    """The "ask user" curiosity action, structured rather than a chat
    message. Surfaced on the dashboard like ApprovalRequest is; an answer
    round-trips into MemoryType.USER via the existing
    MemoryStore.create_user_entry (see curiosity/answers.py).
    """

    __tablename__ = "pending_questions"

    source_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    source_reflection_id: Mapped[int | None] = mapped_column(ForeignKey("reflections.id"), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[QuestionStatus] = mapped_column(Enum(QuestionStatus), default=QuestionStatus.PENDING)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_memory_entry_id: Mapped[str | None] = mapped_column(ForeignKey("memory_entries.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchObjective(UUIDPKMixin, CreatedAtMixin, Base):
    """"Generate research objectives" curiosity action — a structured,
    locally-stored artifact (per user's decision: no live web search this
    round). objective_type distinguishes the in-scope local actions from
    a future out-of-scope one so a later WebSearchTool-backed objective
    type can be added without a migration.
    """

    __tablename__ = "research_objectives"

    source_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    source_reflection_id: Mapped[int | None] = mapped_column(ForeignKey("reflections.id"), nullable=True)
    objective_type: Mapped[str] = mapped_column(String(50))  # "search_memory" | "inspect_previous_work" | "web_search" (future)
    description: Mapped[str] = mapped_column(Text)
    # JSON list of {memory_entry_id, title, score}
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    # Always True this round (local objective types resolve immediately);
    # reserved False for a future async web_search type.
    resolved: Mapped[bool] = mapped_column(Boolean, default=True)
