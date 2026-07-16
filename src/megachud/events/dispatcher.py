from __future__ import annotations

from typing import Callable

from megachud.models.event import Event


class EventDispatcher:
    """Composes multiple on_event-style callbacks into one, preserving
    EventLogger's single-callback contract — EventLogger itself stays
    unchanged. Runs handlers in registration order: ORDER MATTERS. For
    example, TaskCompletionHandler must run before CuriosityHandler, since
    curiosity reads the Reflection row TaskCompletionHandler just created.
    Each handler owns its own DB session (same pattern TaskCompletionHandler
    already uses), so handlers are independent by construction.
    """

    def __init__(self, handlers: list[Callable[[Event], None]]) -> None:
        self._handlers = handlers

    def __call__(self, event: Event) -> None:
        for handler in self._handlers:
            handler(event)
