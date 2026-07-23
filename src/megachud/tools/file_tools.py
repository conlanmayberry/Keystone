from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from megachud.models.approval import RiskLevel
from megachud.tools.base import Tool, ToolResult, ToolValidationError
from megachud.workspace.sandbox import WorkspaceEscapeError, resolve_safe_path

# Files larger than this, or that don't decode as UTF-8 text, are skipped
# by search_files (they're almost certainly binary / not what a text
# search wants, and reading them wastes memory).
_SEARCH_MAX_FILE_BYTES = 1_000_000


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
            metadata={"bytes_written": written, "path": args["path"]},
        )


class AppendFileTool(Tool):
    name = "append_file"
    description = (
        "Append text to the end of a file within the sandboxed workspace "
        "(creating it and parent dirs if needed). Use this instead of "
        "write_file to build up a document across multiple steps without "
        "overwriting what's already there."
    )
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
        with target.open("a", encoding="utf-8") as f:
            f.write(content)
        appended = len(content.encode("utf-8"))
        return ToolResult(
            success=True,
            output=f"appended {appended} bytes to {args['path']}",
            metadata={"bytes_appended": appended, "path": args["path"]},
        )


class ListDirectoryTool(Tool):
    name = "list_directory"
    description = (
        "List the entries (files and subdirectories, with sizes) under a "
        "directory in the sandboxed workspace. Use this to discover what "
        "files exist before reading or searching them."
    )
    risk_level = RiskLevel.LOW

    def __init__(self, workspace_root: Path, max_entries: int = 500) -> None:
        self.workspace_root = workspace_root
        self.max_entries = max_entries

    def validate_args(self, args: dict[str, Any]) -> None:
        if "path" in args and not isinstance(args["path"], str):
            raise ToolValidationError("'path' must be a str if provided")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        rel = args.get("path") or "."
        try:
            target = resolve_safe_path(self.workspace_root, rel)
        except WorkspaceEscapeError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        if not target.is_dir():
            return ToolResult(success=False, output="", error=f"not a directory: {rel!r}")

        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        truncated = len(entries) > self.max_entries
        lines = []
        for entry in entries[: self.max_entries]:
            if entry.is_dir():
                lines.append(f"{entry.name}/")
            else:
                lines.append(f"{entry.name} ({entry.stat().st_size} bytes)")
        output = "\n".join(lines) if lines else "(empty directory)"
        return ToolResult(
            success=True,
            output=output,
            metadata={"count": min(len(entries), self.max_entries), "truncated": truncated, "path": rel},
        )


class SearchFilesTool(Tool):
    name = "search_files"
    description = (
        "Search the text of files under a directory in the sandboxed "
        "workspace for a substring (case-insensitive), returning "
        "file:line matches. Binary and very large files are skipped."
    )
    risk_level = RiskLevel.LOW

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("query"), str) or not args["query"]:
            raise ToolValidationError("'query' (non-empty str) is required")
        if "path" in args and not isinstance(args["path"], str):
            raise ToolValidationError("'path' must be a str if provided")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        rel = args.get("path") or "."
        max_results = args.get("max_results", 50)
        try:
            root = resolve_safe_path(self.workspace_root, rel)
        except WorkspaceEscapeError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        if not root.is_dir():
            return ToolResult(success=False, output="", error=f"not a directory: {rel!r}")

        needle = args["query"].lower()
        matches: list[str] = []
        truncated = False
        for dirpath, _dirs, files in os.walk(root):
            for filename in sorted(files):
                path = Path(dirpath) / filename
                try:
                    if path.stat().st_size > _SEARCH_MAX_FILE_BYTES:
                        continue
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                rel_path = path.relative_to(self.workspace_root).as_posix()
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if needle in line.lower():
                        matches.append(f"{rel_path}:{lineno}: {line.strip()[:200]}")
                        if len(matches) >= max_results:
                            truncated = True
                            break
                if truncated:
                    break
            if truncated:
                break

        output = "\n".join(matches) if matches else "(no matches)"
        return ToolResult(
            success=True,
            output=output,
            metadata={"match_count": len(matches), "truncated": truncated, "query": args["query"]},
        )
