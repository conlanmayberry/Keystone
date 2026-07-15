from __future__ import annotations

import json

from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.task import Task
from megachud.reflection.generator import DeterministicReflectionGenerator


def make_task(**overrides):
    defaults = dict(id="t1", title="t", prompt="p", retry_count=0, result_summary=None)
    defaults.update(overrides)
    return Task(**defaults)


def make_evaluation(checks, success=True):
    return Evaluation(task_id="t1", success=success, checks_json=json.dumps(checks))


def make_event(event_type, tool_name=None, payload=None):
    return Event(task_id="t1", event_type=event_type, tool_name=tool_name, payload_json=json.dumps(payload or {}))


def test_all_checks_pass_no_retries_no_change_indicated():
    gen = DeterministicReflectionGenerator()
    task = make_task(retry_count=0)
    evaluation = make_evaluation([{"name": "tool_calls_succeeded", "passed": True, "detail": "all ok"}])

    draft = gen.generate(task, evaluation, [])

    assert "completed without retries" in draft.what_worked
    assert draft.what_failed == []
    assert draft.wrong_assumptions == []
    assert draft.should_change == ["no change indicated"]
    assert draft.become_long_term_knowledge is False


def test_python_syntax_failure_produces_assumption_and_change():
    gen = DeterministicReflectionGenerator()
    task = make_task()
    evaluation = make_evaluation(
        [{"name": "python_syntax", "passed": False, "detail": "broken.py: invalid syntax"}], success=False
    )

    draft = gen.generate(task, evaluation, [])

    assert "assumed generated code would be syntactically valid" in draft.wrong_assumptions
    assert "validate generated code compiles before writing" in draft.should_change
    assert draft.become_long_term_knowledge is True


def test_retries_produce_assumption():
    gen = DeterministicReflectionGenerator()
    task = make_task(retry_count=2)
    evaluation = make_evaluation([{"name": "tool_calls_succeeded", "passed": True, "detail": "ok"}])

    draft = gen.generate(task, evaluation, [])

    assert "completed without retries" not in draft.what_worked
    assert "assumed the first tool-call attempt would succeed" in draft.wrong_assumptions
    assert "add pre-flight validation to reduce retries" in draft.should_change


def test_no_evaluation_uses_result_summary_and_approval_assumption():
    gen = DeterministicReflectionGenerator()
    task = make_task(result_summary="approval not granted for dummy_irreversible: denied")

    draft = gen.generate(task, None, [])

    assert task.result_summary in draft.what_failed
    assert "assumed the requested action would be approved" in draft.wrong_assumptions
    assert "clarify approval requirements before requesting high-risk actions" in draft.should_change
    assert draft.become_long_term_knowledge is True


def test_tool_result_failure_event_included_in_what_failed():
    gen = DeterministicReflectionGenerator()
    task = make_task(result_summary="tool write_file failed: disk full")
    event = make_event("tool_result", tool_name="write_file", payload={"success": False, "error": "disk full"})

    draft = gen.generate(task, None, [event])

    assert any("write_file failed: disk full" in line for line in draft.what_failed)


def test_workspace_escape_error_produces_assumption():
    gen = DeterministicReflectionGenerator()
    task = make_task()
    evaluation = make_evaluation(
        [{"name": "tool_calls_succeeded", "passed": False, "detail": "1/1 failed"}], success=False
    )
    event = make_event(
        "tool_result",
        tool_name="write_file",
        payload={"success": False, "error": "path escapes workspace root: '../x.txt'"},
    )

    draft = gen.generate(task, evaluation, [event])

    assert "assumed a provided path stayed within the workspace" in draft.wrong_assumptions
    assert "validate paths against the workspace before use" in draft.should_change
