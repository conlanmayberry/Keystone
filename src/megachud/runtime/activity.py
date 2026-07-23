from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator


class ActivityTracker:
    """In-memory, thread-safe view of whether the agent is actively working.

    No such signal existed before: task lifecycle lived only in DB
    `Task.status`, so "is it doing anything right now / how long has it
    been going" couldn't be answered without polling and guessing. This
    is a tiny process-local counter, not persisted — it resets on
    restart, which is correct (a fresh process is doing nothing yet).

    Tasks run on a ThreadPoolExecutor, so every method is guarded by a
    lock. `tracked()` brackets one unit of work; `snapshot()` is a
    read-only view for the /status endpoint.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._start_monotonic = time.monotonic()
        self._in_flight = 0
        # monotonic timestamp of the earliest still-running unit of work,
        # so "working_seconds" measures the current burst, not all-time.
        self._work_started_monotonic: float | None = None
        self._last_activity: datetime | None = None

    @contextmanager
    def tracked(self) -> Iterator[None]:
        self._enter()
        try:
            yield
        finally:
            self._exit()

    def _enter(self) -> None:
        with self._lock:
            if self._in_flight == 0:
                self._work_started_monotonic = time.monotonic()
            self._in_flight += 1
            self._last_activity = datetime.now(timezone.utc)

    def _exit(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            if self._in_flight == 0:
                self._work_started_monotonic = None
            self._last_activity = datetime.now(timezone.utc)

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            working_seconds = (
                now - self._work_started_monotonic if self._work_started_monotonic is not None else None
            )
            return {
                "active": self._in_flight > 0,
                "in_flight": self._in_flight,
                "uptime_seconds": now - self._start_monotonic,
                "working_seconds": working_seconds,
                "last_activity_iso": self._last_activity.isoformat() if self._last_activity else None,
            }


def submit_tracked(
    executor: ThreadPoolExecutor, tracker: ActivityTracker, fn: Callable[..., Any], *args: Any
) -> Future:
    """Submit `fn(*args)` to the executor with its whole run bracketed by
    `tracker.tracked()`, so /status reflects it as in-flight for the run's
    real duration. Used by the task and conversation routes in place of a
    bare `executor.submit`."""

    def _run() -> Any:
        with tracker.tracked():
            return fn(*args)

    return executor.submit(_run)
