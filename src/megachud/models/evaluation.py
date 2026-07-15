from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin


class Evaluation(CreatedAtMixin, Base):
    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    success: Mapped[bool] = mapped_column(Boolean)
    checks_json: Mapped[str] = mapped_column(Text, default="[]")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
