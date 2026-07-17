from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin, UUIDPKMixin


class Agent(UUIDPKMixin, CreatedAtMixin, Base):
    """Structural multi-agent seam — deliberately minimal (no capability
    list, no auth, no process-affinity field). Still exactly one
    orchestrator process runs; this table only gives rows a stable
    identity to be tagged with (Task/Strategy/MemoryEntry/Review) so a
    future multi-agent phase has a foreign key to build on without a
    schema change.
    """

    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
