from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone


class ThoughtLog:
    """Ephemeral, bounded, in-memory ring buffer of the agent's recent
    natural-language "thoughts" — the clarifying questions, plan
    summaries, reflections, and curiosity questions the LLM components
    already produce, surfaced so a human can watch the agent reason.

    Deliberately NOT persisted and deliberately capped: `max_entries`
    bounds how many are kept (oldest fall off), `max_chars` truncates each
    one. This matches the requirement that not every thought is stored
    permanently — the log is a live window, lost on restart, not a record.

    Thread-safe: thoughts are recorded from ThreadPoolExecutor worker
    threads and API request threads alike.
    """

    def __init__(self, max_entries: int = 50, max_chars: int = 400) -> None:
        self._max_chars = max_chars
        self._entries: deque[dict] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def record(self, source: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if len(text) > self._max_chars:
            text = text[: self._max_chars - 1].rstrip() + "…"
        entry = {"source": source, "text": text, "ts": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            self._entries.append(entry)

    def recent(self) -> list[dict]:
        """Newest first."""
        with self._lock:
            return list(reversed(self._entries))
