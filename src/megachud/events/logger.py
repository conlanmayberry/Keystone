from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

from megachud.events.bus import EventBusProtocol
from megachud.models.event import Event


class EventLogger:
    """Single write path into the `events` table — every tool call, approval
    event, and evaluation goes through here, so nothing bypasses structured
    logging.

    `on_event` is an optional synchronous callback fired after every commit
    (e.g. Phase 2's TaskCompletionHandler, which generates a reflection and
    memory entries on task_completed/task_failed). It's a plain callback
    rather than a subscriber on the async EventBus so that it works
    identically whether the caller is the FastAPI app (with a running event
    loop) or a standalone script like scripts/run_dummy_task.py (with none)
    — both go through this same log() method. Defaults to None so every
    existing call site is unaffected.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        bus: EventBusProtocol,
        on_event: Callable[[Event], None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._bus = bus
        self._on_event = on_event

    def log(
        self,
        *,
        event_type: str,
        task_id: str | None = None,
        tool_name: str | None = None,
        duration_ms: int | None = None,
        cost_usd: float | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        evaluation_id: int | None = None,
        reflection: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        session = self._session_factory()
        try:
            event = Event(
                task_id=task_id,
                event_type=event_type,
                tool_name=tool_name,
                duration_ms=duration_ms,
                cost_usd=cost_usd,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                evaluation_id=evaluation_id,
                reflection=reflection,
                payload_json=json.dumps(payload or {}),
            )
            session.add(event)
            session.commit()
            session.refresh(event)
        finally:
            session.close()

        self._bus.publish(
            {
                "id": event.id,
                "timestamp": event.created_at.isoformat(),
                "task_id": event.task_id,
                "event_type": event.event_type,
                "tool_name": event.tool_name,
                "duration_ms": event.duration_ms,
                "payload": payload or {},
            }
        )

        if self._on_event is not None:
            self._on_event(event)

        return event
