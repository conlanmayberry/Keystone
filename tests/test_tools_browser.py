from __future__ import annotations

import pytest

from megachud.browser.session import BrowserSessionManager
from megachud.internet import url_safety
from megachud.orchestrator.context import current_task_id
from megachud.tools.base import ToolValidationError
from megachud.tools.browser_tools import BrowserNavigateTool, BrowserReadTool
from tests.fixtures.fake_browser import FakePage, make_fake_factory


@pytest.fixture
def in_task():
    """Set the ambient task id the browser tools key their session on,
    resetting it after the test so nothing leaks between tests."""
    token = current_task_id.set("task-1")
    try:
        yield "task-1"
    finally:
        current_task_id.reset(token)


def _stub_public_resolver(monkeypatch):
    monkeypatch.setattr(url_safety, "_resolve_hostname", lambda hostname: ["93.184.216.34"])


def _manager(page: FakePage) -> BrowserSessionManager:
    factory, _ = make_fake_factory(page)
    return BrowserSessionManager(page_factory=factory)


def test_navigate_success(monkeypatch, in_task):
    _stub_public_resolver(monkeypatch)
    page = FakePage(title="Example Domain", url="https://example.com/")
    tool = BrowserNavigateTool(_manager(page))

    result = tool.run({"url": "https://example.com/"})

    assert result.success
    assert result.metadata["title"] == "Example Domain"
    assert result.metadata["status_code"] == 200
    assert page.navigations == ["https://example.com/"]


def test_navigate_rejects_unsafe_url_before_launching(monkeypatch, in_task):
    monkeypatch.setattr(url_safety, "_resolve_hostname", lambda hostname: ["127.0.0.1"])
    page = FakePage()
    tool = BrowserNavigateTool(_manager(page))

    result = tool.run({"url": "http://internal.example/"})

    assert not result.success
    assert "non-public address" in result.error
    assert page.navigations == []  # never navigated


def test_navigate_requires_task_context(monkeypatch):
    _stub_public_resolver(monkeypatch)
    # No in_task fixture — contextvar is unset.
    tool = BrowserNavigateTool(_manager(FakePage()))
    result = tool.run({"url": "https://example.com/"})
    assert not result.success
    assert "inside a task" in result.error


def test_navigate_missing_url_raises_validation():
    tool = BrowserNavigateTool(_manager(FakePage()))
    with pytest.raises(ToolValidationError, match="url"):
        tool.run({})


def test_read_text(monkeypatch, in_task):
    _stub_public_resolver(monkeypatch)
    page = FakePage(body_text="the page body text")
    manager = _manager(page)
    # open the page first
    BrowserNavigateTool(manager).run({"url": "https://example.com/"})

    result = BrowserReadTool(manager).run({"mode": "text"})

    assert result.success
    assert result.output == "the page body text"
    assert result.metadata["mode"] == "text"


def test_read_links(monkeypatch, in_task):
    _stub_public_resolver(monkeypatch)
    page = FakePage(links=[{"text": "Home", "href": "https://example.com/home"}])
    manager = _manager(page)
    BrowserNavigateTool(manager).run({"url": "https://example.com/"})

    result = BrowserReadTool(manager).run({"mode": "links"})

    assert result.success
    assert "Home -> https://example.com/home" in result.output
    assert result.metadata["links"][0]["href"] == "https://example.com/home"


def test_read_before_navigate_fails_cleanly(in_task):
    manager = _manager(FakePage())
    result = BrowserReadTool(manager).run({"mode": "text"})
    assert not result.success
    assert "browser_navigate first" in result.error


def test_read_rejects_bad_mode(in_task):
    manager = _manager(FakePage())
    with pytest.raises(ToolValidationError, match="mode"):
        BrowserReadTool(manager).run({"mode": "screenshot"})
