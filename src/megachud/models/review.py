from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin, UUIDPKMixin


class ReviewKind(str, enum.Enum):
    HOURLY = "hourly"
    WEEKLY = "weekly"


class Review(UUIDPKMixin, CreatedAtMixin, Base):
    """A point-in-time historical record — unlike Analytics/BottleneckFinding
    (computed on demand, never persisted), a review is worth keeping so past
    periods can be looked back on."""

    __tablename__ = "reviews"

    kind: Mapped[ReviewKind] = mapped_column(Enum(ReviewKind))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    report_json: Mapped[str] = mapped_column(Text)
