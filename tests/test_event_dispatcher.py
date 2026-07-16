from __future__ import annotations

from megachud.events.dispatcher import EventDispatcher
from megachud.models.event import Event


def test_dispatcher_calls_all_handlers_in_order():
    calls: list[str] = []

    def handler_a(event: Event) -> None:
        calls.append("a")

    def handler_b(event: Event) -> None:
        calls.append("b")

    dispatcher = EventDispatcher([handler_a, handler_b])
    dispatcher(Event(event_type="task_completed"))

    assert calls == ["a", "b"]


def test_dispatcher_passes_the_same_event_to_every_handler():
    seen = []
    dispatcher = EventDispatcher([lambda e: seen.append(e), lambda e: seen.append(e)])
    event = Event(event_type="task_completed", task_id="t1")

    dispatcher(event)

    assert seen[0] is event
    assert seen[1] is event


def test_dispatcher_with_no_handlers_does_nothing():
    dispatcher = EventDispatcher([])
    dispatcher(Event(event_type="task_completed"))  # should not raise
