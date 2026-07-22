from __future__ import annotations

from megachud.browser.cleanup import BrowserSessionCleanupHandler
from megachud.browser.session import BrowserSessionManager
from megachud.models.event import Event
from tests.fixtures.fake_browser import FakePage, make_fake_factory


def _manager_with_open_session(task_id: str):
    factory, counter = make_fake_factory(FakePage())
    manager = BrowserSessionManager(page_factory=factory)
    manager.get_or_create(task_id)
    return manager, counter


def test_cleanup_closes_session_on_task_completed():
    manager, counter = _manager_with_open_session("task-1")
    handler = BrowserSessionCleanupHandler(manager)

    handler(Event(task_id="task-1", event_type="task_completed", payload_json="{}"))

    assert not manager.has_session("task-1")
    assert counter["count"] == 1


def test_cleanup_closes_session_on_task_failed():
    manager, counter = _manager_with_open_session("task-1")
    handler = BrowserSessionCleanupHandler(manager)

    handler(Event(task_id="task-1", event_type="task_failed", payload_json="{}"))

    assert not manager.has_session("task-1")
    assert counter["count"] == 1


def test_cleanup_ignores_unrelated_events():
    manager, counter = _manager_with_open_session("task-1")
    handler = BrowserSessionCleanupHandler(manager)

    handler(Event(task_id="task-1", event_type="tool_result", payload_json="{}"))

    assert manager.has_session("task-1")  # still open
    assert counter["count"] == 0


def test_cleanup_is_a_noop_when_no_session_was_opened():
    factory, counter = make_fake_factory(FakePage())
    manager = BrowserSessionManager(page_factory=factory)
    handler = BrowserSessionCleanupHandler(manager)

    # The overwhelming majority of tasks never open a browser.
    handler(Event(task_id="task-99", event_type="task_completed", payload_json="{}"))

    assert counter["count"] == 0
