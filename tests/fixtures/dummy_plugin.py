"""Test fixture: a well-behaved plugin registering a trivial LOW-risk tool."""

from __future__ import annotations

from typing import Any

from megachud.plugins import RiskLevel, Tool, ToolResult


class DummyPluginTool(Tool):
    name = "dummy_plugin_tool"
    description = "test fixture tool"
    risk_level = RiskLevel.LOW

    def validate_args(self, args: dict[str, Any]) -> None:
        pass

    def run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="dummy plugin ran")


def register(registry) -> None:
    registry.register_tool(DummyPluginTool())
