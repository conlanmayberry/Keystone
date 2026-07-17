from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from megachud.config import Settings
from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.reflection import Reflection
from megachud.models.review import Review, ReviewKind
from megachud.models.strategy import Strategy
from megachud.models.task import Task, TaskStatus
from megachud.review.generator import generate_hourly_review, generate_weekly_review, persist_review
from megachud.routing.engine import RoutingDecision
from megachud.routing.logging import log_routing_decision


def make_settings(tmp_path) -> Settings:
    return Settings(workspace_root=tmp_path / "ws", db_path=tmp_path / "t.db", vault_root=tmp_path / "vault")


def make_succeeded_task(session_factory, title: str, completed_at: datetime) -> str:
    session = session_factory()
    try:
        task = Task(title=title, prompt="p", status=TaskStatus.SUCCEEDED, completed_at=completed_at)
        session.add(task)
        session.commit()
        return task.id
    finally:
        session.close()


def make_failed_task(session_factory, title: str, completed_at: datetime, summary: str) -> str:
    session = session_factory()
    try:
        task = Task(title=title, prompt="p", status=TaskStatus.FAILED, completed_at=completed_at, result_summary=summary)
        session.add(task)
        session.commit()
        return task.id
    finally:
        session.close()


def test_hourly_review_has_no_weekly_only_fields(session_factory, tmp_path):
    settings = make_settings(tmp_path)
    report = generate_hourly_review(session_factory, settings)

    assert report.kind == "hourly"
    assert report.workflow_evolution is None
    assert report.strategy_effectiveness is None
    assert report.model_routing_summary is None
    assert report.experiments_summary is None
    assert report.recommendations is None


def test_weekly_review_populates_weekly_only_fields(session_factory, tmp_path):
    settings = make_settings(tmp_path)
    report = generate_weekly_review(session_factory, settings)

    assert report.kind == "weekly"
    assert report.workflow_evolution is not None
    assert report.strategy_effectiveness is not None
    assert report.model_routing_summary is not None
    assert report.experiments_summary is not None
    assert report.recommendations is not None


def test_accomplishments_and_blockers_reflect_recent_tasks(session_factory, tmp_path):
    settings = make_settings(tmp_path)
    now = datetime.now(timezone.utc)
    make_succeeded_task(session_factory, "shipped the widget", now - timedelta(minutes=10))
    make_failed_task(session_factory, "broke the sprocket", now - timedelta(minutes=5), "tool write_file failed: bad path")

    report = generate_hourly_review(session_factory, settings, now=now)

    assert any("shipped the widget" in line for line in report.accomplishments)
    assert any("broke the sprocket" in line and "bad path" in line for line in report.blockers)


def test_learning_pulls_should_change_from_long_term_reflections(session_factory, tmp_path):
    settings = make_settings(tmp_path)
    now = datetime.now(timezone.utc)
    task_id = make_failed_task(session_factory, "t", now, "s")

    # created_at must be strictly before window_end (= now, captured above);
    # without an explicit value it defaults to construction time, which is
    # a moment AFTER `now` and would fall just outside the window.
    just_before_now = now - timedelta(seconds=1)
    session = session_factory()
    try:
        session.add(Reflection(
            task_id=task_id, become_long_term_knowledge=True, created_at=just_before_now,
            should_change=json.dumps(["validate inputs before writing"]),
        ))
        session.add(Reflection(
            task_id=task_id, become_long_term_knowledge=False, created_at=just_before_now,
            should_change=json.dumps(["should not appear"]),
        ))
        session.commit()
    finally:
        session.close()

    report = generate_hourly_review(session_factory, settings, now=now)

    assert "validate inputs before writing" in report.learning
    assert "should not appear" not in report.learning


def test_model_routing_summary_counts_decisions_in_window(session_factory, tmp_path):
    settings = make_settings(tmp_path)
    event_logger = EventLogger(session_factory, EventBus())
    decision = RoutingDecision(chosen_model="balanced", reason="r", estimated_cost_usd=0.0, candidates_considered=["balanced"])
    log_routing_decision(event_logger, task_id=None, task_type="t", decision=decision)
    log_routing_decision(event_logger, task_id=None, task_type="t", decision=decision)

    report = generate_weekly_review(session_factory, settings)

    assert report.model_routing_summary == {"balanced": 2}


def test_recommendations_reuse_bottleneck_findings(session_factory, tmp_path):
    settings = make_settings(tmp_path)
    session = session_factory()
    try:
        strategy = Strategy(workflow_name="declining_wf", title="t", is_active=True)
        session.add(strategy)
        session.commit()
        strategy_id = strategy.id
    finally:
        session.close()

    event_logger = EventLogger(session_factory, EventBus())
    now = datetime.now(timezone.utc)
    # First half succeeds, second half fails -> strategy_declining_success finding.
    outcomes = [True] * 6 + [False] * 6
    for i, success in enumerate(outcomes):
        completed = now - timedelta(minutes=(len(outcomes) - i))
        session = session_factory()
        try:
            task = Task(
                title=f"t{i}", prompt="p",
                status=TaskStatus.SUCCEEDED if success else TaskStatus.FAILED,
                started_at=completed - timedelta(seconds=1), completed_at=completed,
            )
            session.add(task)
            session.commit()
            task_id = task.id
            session.add(Evaluation(task_id=task_id, success=success, checks_json="[]"))
            session.commit()
        finally:
            session.close()
        event_logger.log(event_type="strategy_invoked", task_id=task_id, payload={"strategy_id": strategy_id, "params": {}})

    report = generate_weekly_review(session_factory, settings, now=now)

    assert any("declining_wf" in line for line in report.recommendations)


def test_persist_review_roundtrips(session_factory, tmp_path):
    settings = make_settings(tmp_path)
    report = generate_hourly_review(session_factory, settings)

    review_id = persist_review(session_factory, report)

    session = session_factory()
    try:
        stored = session.get(Review, review_id)
        assert stored.kind == ReviewKind.HOURLY
        payload = json.loads(stored.report_json)
        assert payload["kind"] == "hourly"
        assert "metrics" in payload
    finally:
        session.close()
