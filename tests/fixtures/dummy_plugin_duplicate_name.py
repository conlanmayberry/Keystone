"""Test fixture: a plugin that tries to register a tool named the same as
a built-in, proving ToolRegistry's duplicate-name check applies uniformly
to plugin tools and that the failure is captured, not an uncaught
exception that crashes the loader.
"""

from __future__ import annotations

from typing import Any

from megachud.plugins import RiskLevel, Tool, ToolResult


class DuplicateNameTool(Tool):
    name = "write_file"  # collides with the built-in WriteFileTool
    description = "duplicate name on purpose"
    risk_level = RiskLevel.LOW

    def validate_args(self, args: dict[str, Any]) -> None:
        pass

    def run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="should never run")


def register(registry) -> None:
    registry.register_tool(DuplicateNameTool())
