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
        """For browser_navigate: opens (lazily launching) this task's
        session, creating it if needed."""
        task_id = current_task_id.get()
        if task_id is None:
            return None, ToolResult(
                success=False, output="", error="browser tools can only run inside a task"
            )
        try:
            return self._manager.get_or_create(task_id), None
        except (BrowserUnavailableError, BrowserSessionLimitError) as exc:
            return None, ToolResult(success=False, output="", error=str(exc))

    def _require_open_page(self) -> tuple[Any, ToolResult | None]:
        """For every tool except navigate: requires a page already opened
        by a prior browser_navigate in this task, rather than silently
        launching a blank one."""
        task_id = current_task_id.get()
        if task_id is None:
            return None, ToolResult(
                success=False, output="", error="browser tools can only run inside a task"
            )
        if not self._manager.has_session(task_id):
            return None, ToolResult(
                success=False, output="", error="no page open — call browser_navigate first"
            )
        return self._manager.get_or_create(task_id), None


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

        session, error = self._require_open_page()
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


# JS run against a click target to classify it — see _is_state_changing.
_ELEMENT_INFO_JS = """el => ({
    tag: el.tagName.toLowerCase(),
    type: (el.getAttribute('type') || '').toLowerCase(),
    inForm: !!el.closest('form'),
    text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().toLowerCase(),
})"""


def _is_state_changing(info: dict[str, Any], denylist: list[str]) -> bool:
    """Best-effort classification of a click target. Honest caveat: this
    inspects static DOM attributes and visible text; a JS onclick handler
    or a control disguised as a plain link can still change state without
    tripping any of these, so this is a guardrail, not a guarantee — the
    approval gate is the real protection, and browser_submit routes there.
    """
    tag = info.get("tag", "")
    type_ = info.get("type", "")
    in_form = bool(info.get("inForm"))
    text = info.get("text", "")

    if type_ in ("submit", "image"):
        return True
    # A <button> with no explicit type defaults to submit inside a form.
    if tag == "button" and type_ not in ("button", "reset") and in_form:
        return True
    return any(word in text for word in denylist)


class BrowserFillTool(_BrowserToolBase):
    name = "browser_fill"
    description = (
        "Type text into a form field on the current page (does not submit "
        "— filling a field cannot change remote state on its own). "
        "Navigate first with browser_navigate."
    )
    risk_level = RiskLevel.MEDIUM

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("selector"), str) or not args["selector"].strip():
            raise ToolValidationError("'selector' (non-empty str) is required")
        if not isinstance(args.get("text"), str):
            raise ToolValidationError("'text' (str) is required")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        session, error = self._require_open_page()
        if error is not None:
            return error
        try:
            session.page.fill(args["selector"], args["text"])
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"fill failed: {exc}")
        return ToolResult(
            success=True, output=f"filled {args['selector']}", metadata={"selector": args["selector"]}
        )


class BrowserClickTool(_BrowserToolBase):
    name = "browser_click"
    description = (
        "Click an element (e.g. a link or a plain button) on the current "
        "page. Refuses anything that looks state-changing (a submit "
        "button, a button inside a form, or text like buy/pay/delete) and "
        "tells you to use browser_submit instead, which is approval-gated. "
        "Navigate first with browser_navigate."
    )
    risk_level = RiskLevel.MEDIUM

    def __init__(self, manager: BrowserSessionManager, *, state_changing_button_text: list[str] | None = None) -> None:
        super().__init__(manager)
        self._denylist = [w.lower() for w in (state_changing_button_text or [])]

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("selector"), str) or not args["selector"].strip():
            raise ToolValidationError("'selector' (non-empty str) is required")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        selector = args["selector"]
        session, error = self._require_open_page()
        if error is not None:
            return error

        try:
            info = session.page.eval_on_selector(selector, _ELEMENT_INFO_JS)
        except Exception:
            return ToolResult(success=False, output="", error=f"no element matches selector {selector!r}")

        if _is_state_changing(info, self._denylist):
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"{selector!r} looks state-changing (submit/form/denylisted text); "
                    "use browser_submit instead — it routes through the human approval gate"
                ),
            )

        try:
            session.page.click(selector)
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"click failed: {exc}")
        return ToolResult(
            success=True, output=f"clicked {selector}", metadata={"selector": selector, "url": session.page.url}
        )


class BrowserSubmitTool(_BrowserToolBase):
    name = "browser_submit"
    description = (
        "Submit a form / click a control that changes remote state (e.g. "
        "a submit button, a purchase or send action). HIGH-RISK: every "
        "call is routed through the human approval gate before it runs. "
        "Navigate and fill any fields first."
    )
    risk_level = RiskLevel.HIGH_IRREVERSIBLE

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("selector"), str) or not args["selector"].strip():
            raise ToolValidationError("'selector' (non-empty str) is required")

    def run(self, args: dict[str, Any]) -> ToolResult:
        # By the time run() is reached, the orchestrator has already
        # obtained human approval (RiskLevel.HIGH_IRREVERSIBLE routes
        # through ApprovalGate.request_and_wait). This tool just performs
        # the approved click.
        self.validate_args(args)
        selector = args["selector"]
        session, error = self._require_open_page()
        if error is not None:
            return error
        try:
            session.page.click(selector)
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"submit click failed: {exc}")
        return ToolResult(
            success=True, output=f"submitted via {selector}", metadata={"selector": selector, "url": session.page.url}
        )
