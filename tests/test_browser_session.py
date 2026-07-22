from __future__ import annotations

import pytest

from megachud.browser.session import (
    BrowserSessionLimitError,
    BrowserSessionManager,
    BrowserUnavailableError,
)
from tests.fixtures.fake_browser import FakePage, make_fake_factory


def test_get_or_create_reuses_within_a_task():
    factory, _ = make_fake_factory(FakePage())
    manager = BrowserSessionManager(page_factory=factory)

    first = manager.get_or_create("task-1")
    second = manager.get_or_create("task-1")

    assert first is second  # reuse across steps of the same task


def test_distinct_tasks_get_distinct_sessions():
    # A factory that returns a fresh page each call.
    def factory(**kwargs):
        from megachud.browser.session import BrowserSession

        return BrowserSession(page=FakePage(), closers=[])

    manager = BrowserSessionManager(page_factory=factory)
    a = manager.get_or_create("task-a")
    b = manager.get_or_create("task-b")

    assert a is not b


def test_close_tears_down_the_session():
    factory, counter = make_fake_factory(FakePage())
    manager = BrowserSessionManager(page_factory=factory)

    manager.get_or_create("task-1")
    assert manager.has_session("task-1")

    manager.close("task-1")
    assert not manager.has_session("task-1")
    assert counter["count"] == 1


def test_close_is_a_noop_for_unknown_task():
    factory, counter = make_fake_factory(FakePage())
    manager = BrowserSessionManager(page_factory=factory)
    manager.close("never-opened")  # must not raise
    assert counter["count"] == 0


def test_max_sessions_cap_is_enforced():
    def factory(**kwargs):
        from megachud.browser.session import BrowserSession

        return BrowserSession(page=FakePage(), closers=[])

    manager = BrowserSessionManager(max_sessions=2, page_factory=factory)
    manager.get_or_create("t1")
    manager.get_or_create("t2")

    with pytest.raises(BrowserSessionLimitError):
        manager.get_or_create("t3")


def test_closing_frees_a_slot_under_the_cap():
    def factory(**kwargs):
        from megachud.browser.session import BrowserSession

        return BrowserSession(page=FakePage(), closers=[])

    manager = BrowserSessionManager(max_sessions=1, page_factory=factory)
    manager.get_or_create("t1")
    manager.close("t1")
    manager.get_or_create("t2")  # slot freed — must not raise


def test_close_all_tears_down_everything():
    page = FakePage()
    factory, counter = make_fake_factory(page)
    manager = BrowserSessionManager(page_factory=factory)
    manager.get_or_create("t1")

    manager.close_all()
    assert not manager.has_session("t1")
    assert counter["count"] == 1


def test_session_close_swallows_teardown_errors():
    from megachud.browser.session import BrowserSession

    def boom() -> None:
        raise RuntimeError("browser already dead")

    session = BrowserSession(page=FakePage(), closers=[boom])
    session.close()  # must not raise


def test_missing_playwright_raises_browser_unavailable(monkeypatch):
    # The default factory lazily imports playwright; simulate it missing.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    manager = BrowserSessionManager()  # real default factory
    with pytest.raises(BrowserUnavailableError, match="playwright is not installed"):
        manager.get_or_create("t1")
