from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from megachud.models.approval import RiskLevel
from megachud.tools.base import Tool, ToolResult, ToolValidationError
from megachud.workspace.sandbox import WorkspaceEscapeError, resolve_safe_path

# subprocess.run(shell=False) never invokes a shell, so these characters have
# no special meaning to the OS once tokenized — this check is a policy-level
# guard against an agent attempting shell-style chaining/redirection syntax,
# checked against parsed tokens (not the raw string) so quoted content like
# `python -c "import time; time.sleep(1)"` isn't falsely flagged.
FORBIDDEN_METACHARACTERS = {"&&", "||", "|", ";", ">", ">>", "<", "`"}


class ShellExecTool(Tool):
    name = "shell_exec"
    description = "Run an allowlisted, non-destructive shell command confined to the sandboxed workspace."
    risk_level = RiskLevel.MEDIUM

    def __init__(
        self,
        workspace_root: Path,
        allowlist: list[str],
        denylist: list[str],
        timeout_seconds: int,
    ) -> None:
        self.workspace_root = workspace_root
        self.allowlist = set(allowlist)
        self.denylist = list(denylist)
        self.timeout_seconds = timeout_seconds

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("command"), str) or not args["command"].strip():
            raise ToolValidationError("'command' (non-empty str) is required")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        command = args["command"]
        cwd_arg = args.get("cwd")

        for denied in self.denylist:
            if command.strip().startswith(denied):
                return ToolResult(success=False, output="", error=f"command not allowed (denylisted): {denied!r}")

        try:
            tokens = shlex.split(command, posix=True)
        except ValueError as exc:
            return ToolResult(success=False, output="", error=f"could not parse command: {exc}")

        if not tokens:
            return ToolResult(success=False, output="", error="empty command")

        for token in tokens:
            if token in FORBIDDEN_METACHARACTERS:
                return ToolResult(success=False, output="", error=f"forbidden shell metacharacter: {token!r}")

        program = tokens[0]
        if program not in self.allowlist:
            return ToolResult(success=False, output="", error=f"command not allowed: {program!r} not in allowlist")

        try:
            cwd = resolve_safe_path(self.workspace_root, cwd_arg) if cwd_arg else self.workspace_root
        except WorkspaceEscapeError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        start = time.monotonic()
        try:
            proc = subprocess.run(
                tokens,
                cwd=cwd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error=f"command timed out after {self.timeout_seconds}s")
        except OSError as exc:
            return ToolResult(success=False, output="", error=f"failed to launch command: {exc}")

        duration_ms = int((time.monotonic() - start) * 1000)
        success = proc.returncode == 0
        return ToolResult(
            success=success,
            output=proc.stdout,
            error=proc.stderr if not success else None,
            metadata={"exit_code": proc.returncode, "duration_ms": duration_ms},
        )
