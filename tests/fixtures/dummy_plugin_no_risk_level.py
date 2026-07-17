"""Test fixture: a plugin registering a Tool subclass that forgot to set
risk_level, to prove PluginRegistry rejects it explicitly rather than
letting it silently reach the real ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from megachud.plugins import Tool, ToolResult


class NoRiskLevelTool(Tool):
    name = "no_risk_level_tool"
    description = "missing risk_level on purpose"
    # risk_level intentionally not set

    def validate_args(self, args: dict[str, Any]) -> None:
        pass

    def run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="should never run")


def register(registry) -> None:
    registry.register_tool(NoRiskLevelTool())
