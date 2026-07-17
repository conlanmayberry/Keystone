from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin, UUIDPKMixin


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(UUIDPKMixin, CreatedAtMixin, Base):
    __tablename__ = "tasks"

    title: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING)
    plan_json: Mapped[str] = mapped_column(Text, default="[]")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Phase 5 structural multi-agent/multi-project seam — nullable, populated
    # from app.state.current_agent_id / settings.project_name at creation
    # time. Existing rows (and rows from scripts that don't set them) stay
    # NULL, which is fine and honest.
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
