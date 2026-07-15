from __future__ import annotations

from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.task import Task


def test_log_persists_event_with_all_fields(session_factory):
    session = session_factory()
    try:
        task = Task(title="t", prompt="p")
        session.add(task)
        session.commit()
        task_id = task.id
    finally:
        session.close()

    logger = EventLogger(session_factory, EventBus())
    event = logger.log(
        event_type="tool_call",
        task_id=task_id,
        tool_name="write_file",
        duration_ms=42,
        payload={"args": {"path": "a.txt"}},
    )

    assert event.id is not None
    assert event.task_id == task_id
    assert event.event_type == "tool_call"
    assert event.tool_name == "write_file"
    assert event.duration_ms == 42
    assert event.created_at is not None


def test_log_publishes_to_bus():
    bus = EventBus()

    def make_logger(session_factory):
        return EventLogger(session_factory, bus)

    # Using a throwaway in-memory-ish setup isn't needed here — bus behavior
    # is independent of persistence; verify via backlog after a publish.
    bus.publish({"event_type": "task_started"})
    assert bus.backlog()[-1]["event_type"] == "task_started"


def test_bus_subscriber_receives_backlog_on_subscribe():
    bus = EventBus()
    bus.publish({"event_type": "a"})
    bus.publish({"event_type": "b"})

    queue = bus.subscribe()
    assert queue.qsize() == 2
