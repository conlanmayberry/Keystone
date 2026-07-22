from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megachud.db import Base
from megachud.models.base import CreatedAtMixin, UUIDPKMixin


class Conversation(UUIDPKMixin, CreatedAtMixin, Base):
    """A chat thread. No title column — a list preview is derived from the
    first message's content rather than storing a redundant field."""

    __tablename__ = "conversations"

    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ConversationMessage(UUIDPKMixin, CreatedAtMixin, Base):
    """One turn of a conversation. `execution_mode` is recorded on the
    message (not just on the eventual Task) because for a "semi_manual"
    proposal, approve_plan happens in a later, separate request — the
    route needs to remember which mode governed that turn to launch the
    Task correctly. `plan_status` is None except on an assistant message
    that proposed a plan still awaiting a semi_manual approval decision
    ("pending"), or one that was explicitly approved/rejected.
    """

    __tablename__ = "conversation_messages"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)

    linked_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    proposed_plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # None|"pending"|"approved"|"rejected"
    execution_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
