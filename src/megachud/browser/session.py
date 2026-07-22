from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = [
    "BrowserSession",
    "BrowserSessionManager",
    "BrowserUnavailableError",
    "BrowserSessionLimitError",
    "PageFactory",
]


class BrowserUnavailableError(Exception):
    """playwright isn't installed, or its Chromium binary isn't present."""


class BrowserSessionLimitError(Exception):
    """max_sessions reached — refuse a new session rather than fan out
    unbounded browser subprocesses."""


@dataclass
class BrowserSession:
    """One task's live browser: a playwright Page (or a test double) plus
    the closers needed to tear down the page/context/browser/playwright it
    owns. `close()` is best-effort and swallows teardown errors — a
    half-dead browser must never propagate out of cleanup."""

    page: Any
    closers: list[Callable[[], None]] = field(default_factory=list)

    def close(self) -> None:
        for closer in reversed(self.closers):
            try:
                closer()
            except Exception:
                pass


# A factory takes launch parameters and returns a ready BrowserSession.
# Production uses _default_page_factory (lazy real Playwright); tests
# inject a fake that returns a recording double — same dependency-injection
# seam Stage A used with httpx.MockTransport / FakeLLMClient.
PageFactory = Callable[..., BrowserSession]


def _default_page_factory(*, headless: bool, viewport: tuple[int, int], nav_timeout_ms: int) -> BrowserSession:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserUnavailableError(
            "playwright is not installed — run `pip install .[browser]` and `playwright install chromium`"
        ) from exc

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=headless)
    except Exception as exc:
        pw.stop()
        raise BrowserUnavailableError(
            f"could not launch Chromium (did you run `playwright install chromium`?): {exc}"
        ) from exc

    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
    page = context.new_page()
    page.set_default_navigation_timeout(nav_timeout_ms)
    page.set_default_timeout(nav_timeout_ms)
    # Order matters at teardown: page/context, then browser, then stop the
    # driver — closers run in reverse of this list.
    return BrowserSession(page=page, closers=[context.close, browser.close, pw.stop])


class BrowserSessionManager:
    """Owns one browser session per task_id. Sessions are created lazily
    on a task's first browser tool call and closed when the task ends (by
    BrowserSessionCleanupHandler, on task_completed/task_failed) — all
    within that task's single worker thread, which is what makes
    Playwright's thread-affine sync API safe here.

    Documented limitation: an unhandled crash mid-task (a tool violating
    the never-raise contract — a bug) could leave one session in the dict
    until process exit. Mitigated by that never-raise convention, unique
    task ids, and close_all() on shutdown; not fully closed because a
    cross-thread browser close is unsafe under Playwright's thread model.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        nav_timeout_ms: int = 15_000,
        max_sessions: int = 4,
        viewport: tuple[int, int] = (1280, 800),
        page_factory: PageFactory | None = None,
    ) -> None:
        self._headless = headless
        self._nav_timeout_ms = nav_timeout_ms
        self._max_sessions = max_sessions
        self._viewport = viewport
        self._page_factory = page_factory or _default_page_factory
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = threading.Lock()

    @property
    def nav_timeout_ms(self) -> int:
        return self._nav_timeout_ms

    def get_or_create(self, task_id: str) -> BrowserSession:
        """Reuse this task's existing session across steps, or launch one.
        Raises BrowserSessionLimitError past the cap and
        BrowserUnavailableError if the browser can't be launched — callers
        (the tools) convert both into clean ToolResult failures. task_ids
        are unique, so there is no stale-same-id case to reconcile."""
        with self._lock:
            existing = self._sessions.get(task_id)
            if existing is not None:
                return existing
            if len(self._sessions) >= self._max_sessions:
                raise BrowserSessionLimitError(
                    f"browser session limit reached (max_sessions={self._max_sessions})"
                )
            session = self._page_factory(
                headless=self._headless, viewport=self._viewport, nav_timeout_ms=self._nav_timeout_ms
            )
            self._sessions[task_id] = session
            return session

    def has_session(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._sessions

    def close(self, task_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(task_id, None)
        if session is not None:
            session.close()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()
