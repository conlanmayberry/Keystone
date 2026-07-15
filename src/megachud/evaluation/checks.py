from __future__ import annotations

import ast
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from megachud.models.task import Task
from megachud.tools.base import ToolResult


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def check_tool_calls_succeeded(task: Task, step_results: list[ToolResult], workspace_root: Path) -> CheckResult:
    failures = [r for r in step_results if not r.success]
    if failures:
        return CheckResult(
            name="tool_calls_succeeded",
            passed=False,
            detail=f"{len(failures)}/{len(step_results)} tool call(s) failed",
        )
    return CheckResult(
        name="tool_calls_succeeded",
        passed=True,
        detail=f"all {len(step_results)} tool call(s) succeeded",
    )


def check_python_syntax(task: Task, step_results: list[ToolResult], workspace_root: Path) -> CheckResult:
    """ast.parse() every .py file this task wrote — real, not stubbed, and
    cheap enough to always run. Catches the most common coding-agent
    failure mode: producing a file that doesn't even parse.
    """
    touched = [
        r.metadata["path"]
        for r in step_results
        if r.success and isinstance(r.metadata.get("path"), str) and r.metadata["path"].endswith(".py")
    ]
    if not touched:
        return CheckResult(name="python_syntax", passed=True, detail="skipped: no .py files touched")

    errors: list[str] = []
    for rel_path in touched:
        full_path = workspace_root / rel_path
        try:
            ast.parse(full_path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            errors.append(f"{rel_path}: {exc}")
        except OSError as exc:
            errors.append(f"{rel_path}: could not read file ({exc})")

    if errors:
        return CheckResult(name="python_syntax", passed=False, detail="; ".join(errors))
    return CheckResult(name="python_syntax", passed=True, detail=f"syntax OK for {len(touched)} file(s)")


def check_tests_pass(
    task: Task,
    step_results: list[ToolResult],
    workspace_root: Path,
    test_command: str | None = None,
) -> CheckResult:
    if not test_command:
        return CheckResult(name="tests_pass", passed=True, detail="skipped: no test command configured")

    try:
        tokens = shlex.split(test_command, posix=True)
        proc = subprocess.run(tokens, cwd=workspace_root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult(name="tests_pass", passed=False, detail=f"failed to run test command: {exc}")

    if proc.returncode == 0:
        return CheckResult(name="tests_pass", passed=True, detail="test command exited 0")
    return CheckResult(
        name="tests_pass",
        passed=False,
        detail=f"test command exited {proc.returncode}: {proc.stderr[:500]}",
    )
