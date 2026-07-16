from __future__ import annotations

import enum

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin, UUIDPKMixin


class ExperimentStatus(str, enum.Enum):
    RUNNING = "running"
    CONCLUDED = "concluded"
    ABANDONED = "abandoned"


class ExperimentRecommendation(str, enum.Enum):
    PROMOTE_VARIANT = "promote_variant"
    KEEP_CONTROL = "keep_control"
    INSUFFICIENT_DATA = "insufficient_data"


class Experiment(UUIDPKMixin, CreatedAtMixin, Base):
    """Compares a control Strategy vs a variant Strategy for the same
    workflow_name. Does not duplicate Task/Evaluation data — outcomes are
    read live via strategy_invoked Event linkage (see
    strategy/metrics.py::outcomes_for_strategy), so this table is just
    the comparison's identity + conclusion.
    """

    __tablename__ = "experiments"

    workflow_name: Mapped[str] = mapped_column(String(200), index=True)
    hypothesis: Mapped[str] = mapped_column(Text)
    control_strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))
    variant_strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))
    minimum_sample_size: Mapped[int] = mapped_column(Integer, default=10)

    status: Mapped[ExperimentStatus] = mapped_column(Enum(ExperimentStatus), default=ExperimentStatus.RUNNING)
    recommendation: Mapped[ExperimentRecommendation | None] = mapped_column(
        Enum(ExperimentRecommendation), nullable=True
    )
    # JSON: {control: {n,success_rate,mean_duration_ms}, variant: {...}, success_rate_delta}
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
