from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Callable

from megachud.evaluation.checks import check_python_syntax, check_tests_pass, check_tool_calls_succeeded
from megachud.models.evaluation import Evaluation
from megachud.models.task import Task
from megachud.tools.base import ToolResult

# check_tests_pass defaults to test_command=None (explicit skip) here;
# construct EvaluationEngine with an overridden checks list bound to
# settings.evaluation.test_command to actually run a test suite.
DEFAULT_CHECKS: list[Callable] = [
    check_tool_calls_succeeded,
    check_python_syntax,
    partial(check_tests_pass, test_command=None),
]


class EvaluationEngine:
    """Implements spec principle 'every task must be evaluated, never assume
    success': a task is only marked succeeded if every check here passes,
    even if all tool calls individually reported success — e.g. all tool
    calls can succeed while writing a file with a syntax error, which this
    catches and the tool-level result alone would not.
    """

    def __init__(self, checks: list[Callable] | None = None) -> None:
        self._checks = checks if checks is not None else DEFAULT_CHECKS

    def evaluate(self, task: Task, step_results: list[ToolResult], workspace_root: Path) -> Evaluation:
        results = [check(task, step_results, workspace_root) for check in self._checks]
        success = all(result.passed for result in results)
        return Evaluation(
            task_id=task.id,
            success=success,
            checks_json=json.dumps([result.__dict__ for result in results]),
        )
