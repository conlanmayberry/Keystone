from __future__ import annotations

from megachud.browser.session import BrowserSessionManager
from megachud.models.event import Event


class BrowserSessionCleanupHandler:
    """Wired into EventDispatcher (like StrategyMetricsHandler): on
    task_completed/task_failed, closes that task's browser session if one
    was opened. Fires inside event_logger.log(), which runs in the task's
    own worker thread — the same thread the browser was created and driven
    in — so the close respects Playwright's thread-affinity. A no-op for
    the overwhelming majority of tasks, which never open a browser.

    Must be wired LAST in the dispatcher list so nothing that still reads
    task state (reflection, metrics, curiosity) runs after teardown.
    """

    def __init__(self, manager: BrowserSessionManager) -> None:
        self._manager = manager

    def __call__(self, event: Event) -> None:
        if event.event_type not in ("task_completed", "task_failed") or event.task_id is None:
            return
        self._manager.close(event.task_id)
