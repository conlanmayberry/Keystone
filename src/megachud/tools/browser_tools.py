from __future__ import annotations

from typing import Any

from megachud.browser.session import (
    BrowserSessionLimitError,
    BrowserSessionManager,
    BrowserUnavailableError,
)
from megachud.internet.url_safety import UrlSafetyError, check_url_safety
from megachud.models.approval import RiskLevel
from megachud.orchestrator.context import current_task_id
from megachud.tools.base import Tool, ToolResult, ToolValidationError

# Cap on the text extracted from a page, so a huge page can't blow up an
# event payload or an LLM context. Mirrors http_fetch's response cap.
_MAX_READ_CHARS = 20_000


class _BrowserToolBase(Tool):
    """Shared plumbing: resolve the current task's session, translate the
    manager's exceptions into clean ToolResults. Subclasses implement
    _run_on_page. run() never raises past validate_args."""

    def __init__(self, manager: BrowserSessionManager) -> None:
        self._manager = manager

    def _session_or_error(self) -> tuple[Any, ToolResult | None]:
        task_id = current_task_id.get()
        if task_id is None:
            return None, ToolResult(
                success=False, output="", error="browser tools can only run inside a task"
            )
        try:
            return self._manager.get_or_create(task_id), None
        except (BrowserUnavailableError, BrowserSessionLimitError) as exc:
            return None, ToolResult(success=False, output="", error=str(exc))


class BrowserNavigateTool(_BrowserToolBase):
    name = "browser_navigate"
    description = (
        "Open a URL in this task's browser (real page, runs JavaScript). "
        "Same SSRF/scheme guard as http_fetch on the URL. Read-oriented — "
        "loads the page so browser_read can extract it."
    )
    risk_level = RiskLevel.MEDIUM  # executes page JS, which can issue its own requests

    def __init__(
        self,
        manager: BrowserSessionManager,
        *,
        domain_allowlist: list[str] | None = None,
        domain_denylist: list[str] | None = None,
    ) -> None:
        super().__init__(manager)
        self._domain_allowlist = domain_allowlist
        self._domain_denylist = domain_denylist

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("url"), str) or not args["url"].strip():
            raise ToolValidationError("'url' (non-empty str) is required")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        url = args["url"]

        try:
            check_url_safety(url, domain_allowlist=self._domain_allowlist, domain_denylist=self._domain_denylist)
        except UrlSafetyError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        session, error = self._session_or_error()
        if error is not None:
            return error

        try:
            response = session.page.goto(url)
            status = response.status if response is not None else None
            title = session.page.title()
            final_url = session.page.url
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"navigation failed: {exc}")

        return ToolResult(
            success=True,
            output=f"navigated to {final_url} ({title!r})",
            metadata={"final_url": final_url, "title": title, "status_code": status},
        )


class BrowserReadTool(_BrowserToolBase):
    name = "browser_read"
    description = (
        "Read the current browser page. mode='text' (visible text, "
        "default), 'links' (anchor texts + hrefs), or 'accessibility' "
        "(the accessibility tree). Navigate first with browser_navigate."
    )
    risk_level = RiskLevel.LOW  # read-only

    _MODES = ("text", "links", "accessibility")

    def validate_args(self, args: dict[str, Any]) -> None:
        mode = args.get("mode", "text")
        if mode not in self._MODES:
            raise ToolValidationError(f"'mode' must be one of {self._MODES}")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        mode = args.get("mode", "text")

        task_id = current_task_id.get()
        if task_id is None:
            return ToolResult(success=False, output="", error="browser tools can only run inside a task")
        if not self._manager.has_session(task_id):
            return ToolResult(
                success=False, output="", error="no page open — call browser_navigate first"
            )
        session, error = self._session_or_error()
        if error is not None:
            return error

        try:
            if mode == "text":
                text = session.page.inner_text("body")
                truncated = len(text) > _MAX_READ_CHARS
                return ToolResult(
                    success=True,
                    output=text[:_MAX_READ_CHARS],
                    metadata={"mode": mode, "url": session.page.url, "truncated": truncated},
                )
            if mode == "links":
                links = session.page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => ({text: (e.innerText||'').trim(), href: e.href}))",
                )
                lines = "\n".join(f"- {link['text']} -> {link['href']}" for link in links) or "(no links)"
                return ToolResult(
                    success=True,
                    output=lines[:_MAX_READ_CHARS],
                    metadata={"mode": mode, "url": session.page.url, "links": links},
                )
            snapshot = session.page.accessibility.snapshot()
            return ToolResult(
                success=True,
                output=str(snapshot)[:_MAX_READ_CHARS],
                metadata={"mode": mode, "url": session.page.url},
            )
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"read failed: {exc}")
