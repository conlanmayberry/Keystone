from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPKMixin:
    id: Mapped[str] = mapped_column(primary_key=True, default=new_uuid)


class CreatedAtMixin:
    # Indexed: analytics, reviews, and bottleneck detection all window on
    # created_at across several tables — without this every windowed query
    # is a full table scan in SQLite.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
