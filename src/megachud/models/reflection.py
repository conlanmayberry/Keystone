from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin


class Reflection(CreatedAtMixin, Base):
    """Structured lessons generated after a completed task, per the spec's
    5 reflection questions. A dedicated table rather than reusing the
    existing (and still unused) Event.reflection column — a reflection is a
    multi-field structured object, not a sentence; Event.reflection remains
    reserved for a possible future finer-grained per-event annotation.
    """

    __tablename__ = "reflections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    evaluation_id: Mapped[int | None] = mapped_column(ForeignKey("evaluations.id"), nullable=True)

    what_worked: Mapped[str] = mapped_column(Text, default="[]")
    what_failed: Mapped[str] = mapped_column(Text, default="[]")
    wrong_assumptions: Mapped[str] = mapped_column(Text, default="[]")
    should_change: Mapped[str] = mapped_column(Text, default="[]")
    become_long_term_knowledge: Mapped[bool] = mapped_column(Boolean, default=False)

    # Provenance of which generator produced this — the swap point for a
    # future LLM-backed ReflectionGenerator.
    generator: Mapped[str] = mapped_column(String(50), default="deterministic_v1")
