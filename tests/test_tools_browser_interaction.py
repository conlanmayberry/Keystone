from __future__ import annotations

import threading
import time

import pytest

from megachud.browser.session import BrowserSessionManager
from megachud.internet import url_safety
from megachud.models.approval import ApprovalRequest
from megachud.models.task import TaskStatus
from megachud.orchestrator.context import current_task_id
from megachud.tools.base import ToolValidationError
from megachud.tools.browser_tools import (
    BrowserClickTool,
    BrowserFillTool,
    BrowserNavigateTool,
    BrowserSubmitTool,
)
from tests.fixtures.fake_browser import FakePage, make_fake_factory
from tests.test_orchestrator_engine import create_task, make_orchestrator

DENYLIST = ["buy", "pay", "delete", "submit"]


@pytest.fixture
def in_task():
    token = current_task_id.set("task-1")
    try:
        yield "task-1"
    finally:
        current_task_id.reset(token)


def _manager(page: FakePage) -> BrowserSessionManager:
    factory, _ = make_fake_factory(page)
    return BrowserSessionManager(page_factory=factory)


def _open(manager: BrowserSessionManager, task_id: str = "task-1") -> None:
    # browser_fill/click/submit require an already-open page.
    manager.get_or_create(task_id)


# --- browser_fill ---

def test_fill_types_into_field(in_task):
    page = FakePage()
    manager = _manager(page)
    _open(manager)
    result = BrowserFillTool(manager).run({"selector": "#q", "text": "hello"})
    assert result.success
    assert page.fills == [("#q", "hello")]


def test_fill_requires_open_page(in_task):
    result = BrowserFillTool(_manager(FakePage())).run({"selector": "#q", "text": "x"})
    assert not result.success
    assert "browser_navigate first" in result.error


def test_fill_validates_args():
    with pytest.raises(ToolValidationError):
        BrowserFillTool(_manager(FakePage())).run({"selector": "#q"})


# --- browser_click heuristic ---

def _click_tool(page: FakePage):
    manager = _manager(page)
    _open(manager)
    return BrowserClickTool(manager, state_changing_button_text=DENYLIST), page


def test_click_plain_link_is_allowed(in_task):
    page = FakePage(elements={"#home": {"tag": "a", "type": "", "inForm": False, "text": "home"}})
    tool, page = _click_tool(page)
    result = tool.run({"selector": "#home"})
    assert result.success
    assert page.clicks == ["#home"]


def test_click_type_submit_is_refused(in_task):
    page = FakePage(elements={"#go": {"tag": "button", "type": "submit", "inForm": True, "text": "go"}})
    tool, page = _click_tool(page)
    result = tool.run({"selector": "#go"})
    assert not result.success
    assert "browser_submit" in result.error
    assert page.clicks == []


def test_click_button_inside_form_is_refused(in_task):
    page = FakePage(elements={"#b": {"tag": "button", "type": "", "inForm": True, "text": "go"}})
    tool, page = _click_tool(page)
    result = tool.run({"selector": "#b"})
    assert not result.success
    assert "browser_submit" in result.error


def test_click_denylisted_text_is_refused(in_task):
    page = FakePage(elements={"#x": {"tag": "a", "type": "", "inForm": False, "text": "buy now"}})
    tool, page = _click_tool(page)
    result = tool.run({"selector": "#x"})
    assert not result.success
    assert "browser_submit" in result.error
    assert page.clicks == []


def test_click_plain_button_not_in_form_is_allowed(in_task):
    page = FakePage(elements={"#toggle": {"tag": "button", "type": "button", "inForm": False, "text": "expand"}})
    tool, page = _click_tool(page)
    result = tool.run({"selector": "#toggle"})
    assert result.success
    assert page.clicks == ["#toggle"]


def test_click_missing_element_fails_cleanly(in_task):
    page = FakePage(elements={})
    tool, page = _click_tool(page)
    result = tool.run({"selector": "#nope"})
    assert not result.success
    assert "no element matches" in result.error


# --- browser_submit unit ---

def test_submit_clicks_the_control(in_task):
    page = FakePage()
    manager = _manager(page)
    _open(manager)
    result = BrowserSubmitTool(manager).run({"selector": "#checkout"})
    assert result.success
    assert page.clicks == ["#checkout"]


def test_submit_is_high_irreversible():
    from megachud.models.approval import RiskLevel

    assert BrowserSubmitTool(_manager(FakePage())).risk_level == RiskLevel.HIGH_IRREVERSIBLE


# --- orchestrator-level: browser_submit is approval-gated ---

def _browser_orchestrator(session_factory, tmp_workspace, page, monkeypatch):
    monkeypatch.setattr(url_safety, "_resolve_hostname", lambda hostname: ["93.184.216.34"])
    manager = _manager(page)
    tools = [BrowserNavigateTool(manager), BrowserSubmitTool(manager)]
    return make_orchestrator(session_factory, tmp_workspace, extra_tools=tools)


def test_browser_submit_routes_through_approval_and_runs_on_approve(session_factory, tmp_workspace, monkeypatch):
    page = FakePage()
    orchestrator, gate = _browser_orchestrator(session_factory, tmp_workspace, page, monkeypatch)
    plan = [
        {"tool_name": "browser_navigate", "args": {"url": "https://example.com/"}},
        {"tool_name": "browser_submit", "args": {"selector": "#checkout"}},
    ]
    task_id = create_task(session_factory, plan)

    def approve_soon():
        time.sleep(0.15)
        session = session_factory()
        try:
            approval = session.query(ApprovalRequest).filter_by(task_id=task_id).one()
            approval_id = approval.id
        finally:
            session.close()
        gate.resolve(approval_id, approved=True, note="ok", resolved_by="tester")

    thread = threading.Thread(target=approve_soon)
    thread.start()
    result = orchestrator.run_task(task_id)
    thread.join()

    assert result.status == TaskStatus.SUCCEEDED
    assert page.clicks == ["#checkout"]


def test_browser_submit_denied_never_clicks(session_factory, tmp_workspace, monkeypatch):
    page = FakePage()
    orchestrator, gate = _browser_orchestrator(session_factory, tmp_workspace, page, monkeypatch)
    plan = [
        {"tool_name": "browser_navigate", "args": {"url": "https://example.com/"}},
        {"tool_name": "browser_submit", "args": {"selector": "#checkout"}},
    ]
    task_id = create_task(session_factory, plan)

    def deny_soon():
        time.sleep(0.15)
        session = session_factory()
        try:
            approval = session.query(ApprovalRequest).filter_by(task_id=task_id).one()
            approval_id = approval.id
        finally:
            session.close()
        gate.resolve(approval_id, approved=False, note="no", resolved_by="tester")

    thread = threading.Thread(target=deny_soon)
    thread.start()
    result = orchestrator.run_task(task_id)
    thread.join()

    assert result.status == TaskStatus.FAILED
    assert page.clicks == []  # the submit never ran
