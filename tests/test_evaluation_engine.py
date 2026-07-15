from __future__ import annotations

import json

from megachud.evaluation.checks import check_python_syntax, check_tests_pass, check_tool_calls_succeeded
from megachud.evaluation.engine import EvaluationEngine
from megachud.models.task import Task
from megachud.tools.base import ToolResult


def make_task():
    return Task(id="t1", title="t", prompt="p")


def test_all_checks_pass_marks_evaluation_success(tmp_workspace):
    task = make_task()
    step_results = [ToolResult(success=True, output="ok", metadata={"path": "ok.py"})]
    (tmp_workspace / "ok.py").write_text("print(1)\n", encoding="utf-8")

    engine = EvaluationEngine()
    evaluation = engine.evaluate(task, step_results, tmp_workspace)

    assert evaluation.success is True
    checks = json.loads(evaluation.checks_json)
    assert all(c["passed"] for c in checks)


def test_failed_tool_call_fails_evaluation(tmp_workspace):
    task = make_task()
    step_results = [ToolResult(success=False, output="", error="boom")]

    engine = EvaluationEngine()
    evaluation = engine.evaluate(task, step_results, tmp_workspace)

    assert evaluation.success is False


def test_syntax_error_fails_evaluation_even_if_tool_call_succeeded(tmp_workspace):
    task = make_task()
    (tmp_workspace / "broken.py").write_text("def f(:\n", encoding="utf-8")
    step_results = [ToolResult(success=True, output="wrote", metadata={"path": "broken.py"})]

    engine = EvaluationEngine()
    evaluation = engine.evaluate(task, step_results, tmp_workspace)

    assert evaluation.success is False
    checks = json.loads(evaluation.checks_json)
    syntax_check = next(c for c in checks if c["name"] == "python_syntax")
    assert syntax_check["passed"] is False
    assert "broken.py" in syntax_check["detail"]


def test_check_tool_calls_succeeded_reports_ratio(tmp_workspace):
    task = make_task()
    results = [ToolResult(success=True, output=""), ToolResult(success=False, output="", error="x")]
    result = check_tool_calls_succeeded(task, results, tmp_workspace)
    assert result.passed is False
    assert "1/2" in result.detail


def test_check_python_syntax_skips_when_no_py_files_touched(tmp_workspace):
    task = make_task()
    result = check_python_syntax(task, [ToolResult(success=True, output="", metadata={"path": "notes.txt"})], tmp_workspace)
    assert result.passed is True
    assert "skipped" in result.detail


def test_check_tests_pass_skips_when_no_command_configured(tmp_workspace):
    task = make_task()
    result = check_tests_pass(task, [], tmp_workspace, test_command=None)
    assert result.passed is True
    assert "skipped" in result.detail


def test_check_tests_pass_runs_configured_command(tmp_workspace):
    task = make_task()
    result = check_tests_pass(task, [], tmp_workspace, test_command="python -c \"import sys; sys.exit(0)\"")
    assert result.passed is True


def test_check_tests_pass_fails_on_nonzero_exit(tmp_workspace):
    task = make_task()
    result = check_tests_pass(task, [], tmp_workspace, test_command="python -c \"import sys; sys.exit(1)\"")
    assert result.passed is False
