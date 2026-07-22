from __future__ import annotations

import os

import pytest

from megachud.browser.session import BrowserSessionManager
from megachud.orchestrator.context import current_task_id
from megachud.tools.browser_tools import BrowserNavigateTool, BrowserReadTool

# Opt-in only: this is the one test that launches a real Chromium. Normal
# runs and CI never touch a browser (the rest of the suite uses the fake
# page double). Run it deliberately with:
#   MEGACHUD_BROWSER_E2E=1 pytest tests/test_browser_e2e.py
# after `playwright install chromium`.
pytestmark = pytest.mark.skipif(
    os.environ.get("MEGACHUD_BROWSER_E2E") != "1",
    reason="set MEGACHUD_BROWSER_E2E=1 (and run `playwright install chromium`) to run the real-browser e2e",
)


def test_real_chromium_navigate_and_read():
    manager = BrowserSessionManager(headless=True)
    token = current_task_id.set("e2e-task")
    try:
        nav = BrowserNavigateTool(manager).run({"url": "https://example.com/"})
        assert nav.success, nav.error
        assert "Example Domain" in nav.metadata["title"]

        read = BrowserReadTool(manager).run({"mode": "text"})
        assert read.success, read.error
        assert "Example Domain" in read.output
    finally:
        manager.close("e2e-task")
        current_task_id.reset(token)
