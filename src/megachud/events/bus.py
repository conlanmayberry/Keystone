from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, Protocol


class EventBusProtocol(Protocol):
    """Phase 5 swap-point formalization of the interface EventBus already
    committed to since Phase 1 (see its docstring). A Protocol, not an ABC,
    since EventBus is a concrete class today, not a subclass hierarchy
    waiting to be created — this lets a future cross-process/cross-agent
    broker satisfy the same interface without EventBus needing to change or
    without forcing inheritance onto the one working implementation.
    """

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None: ...
    def publish(self, event: dict[str, Any]) -> None: ...
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]: ...
    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None: ...
    def backlog(self) -> list[dict[str, Any]]: ...


class EventBus:
    """In-process pub/sub for fanning events out to WebSocket clients.

    Seeds the "event bus" named in the spec's Future Direction section —
    kept in-process for Phase 1 (no Redis/Kafka), but publish/subscribe is
    a stable interface a later phase can re-back without touching callers.

    Safe to use with zero subscribers and no bound event loop (the case for
    Phase 1's orchestrator/tests, which run synchronously) — publish() just
    appends to the backlog. Once a FastAPI app binds its running loop
    (Step 5), publish() marshals into that loop so cross-thread queue
    access is safe.
    """

    def __init__(self, backlog_size: int = 200) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._backlog: deque[dict[str, Any]] = deque(maxlen=backlog_size)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: dict[str, Any]) -> None:
        self._backlog.append(event)
        for queue in list(self._subscribers):
            if self._loop is not None:
                self._loop.call_soon_threadsafe(queue.put_nowait, event)
            else:
                queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for event in self._backlog:
            queue.put_nowait(event)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def backlog(self) -> list[dict[str, Any]]:
        return list(self._backlog)
