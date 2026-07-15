from __future__ import annotations

from typing import Any

from megachud.models.approval import RiskLevel
from megachud.tools.base import Tool, ToolResult


class DummyIrreversibleTool(Tool):
    """Test-only high-risk tool: proves the approval gate blocks execution
    until a human resolves the request, even though no real
    HIGH_IRREVERSIBLE tool ships in Phase 1.
    """

    name = "dummy_irreversible"
    description = "Test-only stand-in for a future irreversible tool (e.g. web purchase, send email)."
    risk_level = RiskLevel.HIGH_IRREVERSIBLE

    def validate_args(self, args: dict[str, Any]) -> None:
        pass

    def run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="dummy irreversible action executed")
