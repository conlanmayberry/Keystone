from __future__ import annotations

import enum

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin, UUIDPKMixin


class StrategyOrigin(str, enum.Enum):
    SEED = "seed"
    EXPERIMENT_VARIANT = "experiment_variant"


class Strategy(UUIDPKMixin, CreatedAtMixin, Base):
    """A reusable, parameterized plan template. One row = one concrete
    version of a procedure. "Workflow" (spec term) is NOT a separate
    table: a workflow is the set of Strategy rows sharing workflow_name,
    with exactly one is_active=True at a time — the active row IS the
    current workflow version. Promotion flips is_active across two rows
    in one transaction (see strategy/promotion.py).
    """

    __tablename__ = "strategies"

    workflow_name: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    # Parameterized plan template: JSON list of {tool_name, args} where arg
    # string values may contain "{param_name}" placeholders, substituted at
    # invocation time by strategy/invoker.py::render_plan.
    plan_template_json: Mapped[str] = mapped_column(Text, default="[]")
    # JSON list[str] of required parameter names, for validation/UI.
    parameters_json: Mapped[str] = mapped_column(Text, default="[]")
    # JSON list[str] free-form applicability tags (spec: "applicability").
    tags_json: Mapped[str] = mapped_column(Text, default="[]")

    origin: Mapped[StrategyOrigin] = mapped_column(Enum(StrategyOrigin), default=StrategyOrigin.SEED)
    # Set when origin == EXPERIMENT_VARIANT: the strategy this one was
    # compared against.
    parent_strategy_id: Mapped[str | None] = mapped_column(ForeignKey("strategies.id"), nullable=True)

    # Rolling metrics, updated incrementally by strategy/metrics.py after
    # every task invoked from this strategy — not a time-series table,
    # sample_count makes the running mean/rate recomputable without
    # re-scanning tasks.
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    mean_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    mean_duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    mean_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Phase 5 structural multi-agent/multi-project seam — see task.py's
    # matching columns for the full rationale.
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    @property
    def success_rate(self) -> float:
        return self.success_count / self.sample_count if self.sample_count else 0.0
