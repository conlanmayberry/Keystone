from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from megachud.analytics.report import build_analytics_report
from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.experiment import Experiment, ExperimentRecommendation, ExperimentStatus
from megachud.models.reflection import Reflection
from megachud.models.strategy import Strategy
from megachud.models.task import Task, TaskStatus

NOW = datetime.now(timezone.utc)
WINDOW_START = NOW - timedelta(hours=1)
WINDOW_END = NOW + timedelta(hours=1)


def make_task(session_factory, status: TaskStatus, created_at: datetime = NOW) -> str:
    session = session_factory()
    try:
        task = Task(title="t", prompt="p", status=status, created_at=created_at)
        session.add(task)
        session.commit()
        return task.id
    finally:
        session.close()


def make_event(session_factory, event_type: str, created_at: datetime = NOW, **kwargs) -> None:
    session = session_factory()
    try:
        event = Event(event_type=event_type, created_at=created_at, payload_json=json.dumps(kwargs.pop("payload", {})), **kwargs)
        session.add(event)
        session.commit()
    finally:
        session.close()


def test_task_counts_by_status_within_window(session_factory):
    make_task(session_factory, TaskStatus.SUCCEEDED)
    make_task(session_factory, TaskStatus.SUCCEEDED)
    make_task(session_factory, TaskStatus.FAILED)
    make_task(session_factory, TaskStatus.SUCCEEDED, created_at=NOW - timedelta(days=5))  # outside window

    report = build_analytics_report(session_factory, WINDOW_START, WINDOW_END)

    assert report.task_counts_by_status == {"succeeded": 2, "failed": 1}


def test_tool_call_counts_and_failure_rates(session_factory):
    make_event(session_factory, "tool_result", tool_name="write_file", payload={"success": True})
    make_event(session_factory, "tool_result", tool_name="write_file", payload={"success": True})
    make_event(session_factory, "tool_result", tool_name="write_file", payload={"success": False})
    make_event(session_factory, "tool_result", tool_name="shell_exec", payload={"success": False})

    report = build_analytics_report(session_factory, WINDOW_START, WINDOW_END)

    assert report.tool_call_counts == {"write_file": 3, "shell_exec": 1}
    assert report.tool_failure_rates["write_file"] == pytest.approx(1 / 3)
    assert report.tool_failure_rates["shell_exec"] == 1.0


def test_event_counts_by_type(session_factory):
    make_event(session_factory, "task_started")
    make_event(session_factory, "task_completed")
    make_event(session_factory, "task_completed")

    report = build_analytics_report(session_factory, WINDOW_START, WINDOW_END)

    assert report.event_counts_by_type == {"task_started": 1, "task_completed": 2}


def test_strategy_success_rates_reflects_current_active_strategy(session_factory):
    session = session_factory()
    try:
        strategy = Strategy(workflow_name="wf", title="t", is_active=True, sample_count=4, success_count=3)
        session.add(strategy)
        session.commit()
    finally:
        session.close()

    report = build_analytics_report(session_factory, WINDOW_START, WINDOW_END)

    assert report.strategy_success_rates == {"wf": 0.75}


def test_experiment_outcome_counts(session_factory):
    session = session_factory()
    try:
        session.add(Strategy(id="c1", workflow_name="wf", title="control"))
        session.add(Strategy(id="v1", workflow_name="wf", title="variant"))
        session.commit()
        session.add(Experiment(workflow_name="wf", hypothesis="h", control_strategy_id="c1", variant_strategy_id="v1", recommendation=ExperimentRecommendation.PROMOTE_VARIANT, status=ExperimentStatus.CONCLUDED))
        session.add(Experiment(workflow_name="wf", hypothesis="h", control_strategy_id="c1", variant_strategy_id="v1", recommendation=None, status=ExperimentStatus.RUNNING))
        session.commit()
    finally:
        session.close()

    report = build_analytics_report(session_factory, WINDOW_START, WINDOW_END)

    assert report.experiment_outcome_counts == {"promote_variant": 1, "pending": 1}


def test_become_long_term_knowledge_rate(session_factory):
    session = session_factory()
    try:
        task = Task(title="t", prompt="p")
        session.add(task)
        session.commit()
        session.add(Reflection(task_id=task.id, become_long_term_knowledge=True))
        session.add(Reflection(task_id=task.id, become_long_term_knowledge=False))
        session.add(Reflection(task_id=task.id, become_long_term_knowledge=False))
        session.commit()
    finally:
        session.close()

    report = build_analytics_report(session_factory, WINDOW_START, WINDOW_END)

    assert report.become_long_term_knowledge_rate == pytest.approx(1 / 3)


def test_no_reflections_gives_zero_rate_not_division_error(session_factory):
    report = build_analytics_report(session_factory, WINDOW_START, WINDOW_END)
    assert report.become_long_term_knowledge_rate == 0.0


def test_cost_data_unavailable_when_no_event_has_cost(session_factory):
    make_event(session_factory, "tool_result", tool_name="write_file", payload={"success": True})

    report = build_analytics_report(session_factory, WINDOW_START, WINDOW_END)

    assert report.cost_data_available is False
    assert report.total_cost_usd == 0.0


def test_cost_data_available_once_one_event_has_cost_set(session_factory):
    make_event(session_factory, "tool_result", tool_name="write_file", cost_usd=0.0, tokens_input=10, tokens_output=5)
    make_event(session_factory, "tool_result", tool_name="write_file")

    report = build_analytics_report(session_factory, WINDOW_START, WINDOW_END)

    # A genuine free ($0.00) cost still counts as "data available" — the
    # signal is whether cost_usd was ever explicitly set (not None), not
    # whether it's nonzero.
    assert report.cost_data_available is True
    assert report.total_cost_usd == 0.0
    assert report.total_tokens_input == 10
    assert report.total_tokens_output == 5
