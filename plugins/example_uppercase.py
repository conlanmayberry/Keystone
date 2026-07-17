"""Example MegaChud plugin: a trivial LOW-risk tool that uppercases text.

Enable by adding "example_uppercase" to plugins.enabled_local in
config/local.yaml. See plugins/README.md for the full mechanism and the
safety model — this file is a working reference, not a template to be
trusted blindly for real workloads.
"""

from __future__ import annotations

from typing import Any

from megachud.plugins import RiskLevel, Tool, ToolResult, ToolValidationError


class UppercaseTool(Tool):
    name = "uppercase_text"
    description = "Returns the given text converted to uppercase. Example plugin tool."
    risk_level = RiskLevel.LOW

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("text"), str):
            raise ToolValidationError("'text' (str) is required")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        text = args["text"]
        return ToolResult(success=True, output=text.upper(), metadata={"original_length": len(text)})


def register(registry) -> None:
    registry.register_tool(UppercaseTool())
