from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from megachud.models.evaluation import Evaluation
from megachud.models.task import Task
from megachud.tools.base import ToolResult

# Populated with real checks (tool success, python syntax, test command) in
# Phase 1 Step 4 — evaluation/checks.py. Empty here means "no checks
# configured yet", not "assume success"; EvaluationEngine.evaluate still
# only returns success=True because `all([])` is vacuously true, which is
# an explicit, visible default (checks_json == "[]"), not a silent skip.
DEFAULT_CHECKS: list[Callable] = []


class EvaluationEngine:
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
