from __future__ import annotations

from pathlib import Path
from typing import Any

from megachud.models.approval import RiskLevel
from megachud.tools.base import Tool, ToolResult, ToolValidationError
from megachud.workspace.sandbox import WorkspaceEscapeError, resolve_safe_path


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a text file within the sandboxed workspace."
    risk_level = RiskLevel.LOW

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("path"), str):
            raise ToolValidationError("'path' (str) is required")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        try:
            target = resolve_safe_path(self.workspace_root, args["path"])
        except WorkspaceEscapeError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        if not target.is_file():
            return ToolResult(success=False, output="", error=f"file not found: {args['path']!r}")

        content = target.read_text(encoding="utf-8")
        return ToolResult(success=True, output=content, metadata={"bytes_read": len(content.encode("utf-8"))})


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write a text file within the sandboxed workspace, creating parent dirs as needed."
    risk_level = RiskLevel.MEDIUM

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("path"), str):
            raise ToolValidationError("'path' (str) is required")
        if not isinstance(args.get("content"), str):
            raise ToolValidationError("'content' (str) is required")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        try:
            target = resolve_safe_path(self.workspace_root, args["path"])
        except WorkspaceEscapeError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        target.parent.mkdir(parents=True, exist_ok=True)
        content = args["content"]
        target.write_text(content, encoding="utf-8")
        written = len(content.encode("utf-8"))
        return ToolResult(
            success=True,
            output=f"wrote {written} bytes to {args['path']}",
            metadata={"bytes_written": written},
        )
