from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.approval import ApprovalStatus
from megachud.models.base import CreatedAtMixin, UUIDPKMixin


class PromotionRequest(UUIDPKMixin, CreatedAtMixin, Base):
    """Human sign-off gate for promoting a challenger Strategy to active,
    deliberately SEPARATE from ApprovalRequest rather than a
    generalization of it. ApprovalRequest is tightly Tool-shaped
    (tool_name, risk_level) and consumed by ApprovalGate's blocking
    DB-poll tied directly to Orchestrator.run_task's call stack; a
    promotion is an out-of-band, human-paced review action with no task
    blocked on it. Reuses only the ApprovalStatus enum (pure data reuse,
    zero coupling to ApprovalGate's blocking behavior).
    """

    __tablename__ = "promotion_requests"

    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"))
    workflow_name: Mapped[str] = mapped_column(String(200))
    from_strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))
    to_strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))
    justification: Mapped[str] = mapped_column(Text)

    status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
