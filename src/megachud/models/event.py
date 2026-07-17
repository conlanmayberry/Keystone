from __future__ import annotations

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin


class Event(CreatedAtMixin, Base):
    """Structured event log: one row per important thing that happens.

    `timestamp` is `created_at` from CreatedAtMixin. Every field required by
    the Engineering Standards logging spec (timestamp, task id, tool,
    duration, cost, evaluation, reflection) has a column here, even where
    unused until later phases (cost/tokens/reflection).
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # task_id/event_type indexed: SQLite doesn't index FKs, and events is
    # the highest-volume table — strategy metrics, curiosity, analytics,
    # and bottleneck detection all filter on these.
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluation_id: Mapped[int | None] = mapped_column(ForeignKey("evaluations.id"), nullable=True)
    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
