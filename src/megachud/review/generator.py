from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from megachud.analytics.report import AnalyticsReport, build_analytics_report
from megachud.bottleneck.finder import find_bottlenecks
from megachud.config import Settings
from megachud.models.event import Event
from megachud.models.experiment import Experiment
from megachud.models.reflection import Reflection
from megachud.models.review import Review, ReviewKind
from megachud.models.strategy import Strategy
from megachud.models.task import Task, TaskStatus

MAX_LISTED_ITEMS = 10


@dataclass
class ReviewReport:
    kind: str
    window_start: datetime
    window_end: datetime
    accomplishments: list[str]
    blockers: list[str]
    learning: list[str]
    costs: dict
    metrics: AnalyticsReport
    workflow_evolution: list[dict] | None = None
    strategy_effectiveness: list[dict] | None = None
    model_routing_summary: dict | None = None
    experiments_summary: list[dict] | None = None
    recommendations: list[str] | None = None


def _accomplishments(session: Session, window_start: datetime, window_end: datetime) -> list[str]:
    succeeded = (
        session.query(Task)
        .filter(Task.status == TaskStatus.SUCCEEDED, Task.completed_at >= window_start, Task.completed_at < window_end)
        .order_by(Task.completed_at.desc())
        .all()
    )
    lines = [f"Succeeded: {t.title}" for t in succeeded[:MAX_LISTED_ITEMS]]
    if len(succeeded) > MAX_LISTED_ITEMS:
        lines.append(f"...and {len(succeeded) - MAX_LISTED_ITEMS} more succeeded tasks")
    return lines


def _blockers(session: Session, window_start: datetime, window_end: datetime) -> list[str]:
    failed = (
        session.query(Task)
        .filter(Task.status == TaskStatus.FAILED, Task.completed_at >= window_start, Task.completed_at < window_end)
        .order_by(Task.completed_at.desc())
        .all()
    )
    awaiting = (
        session.query(Task)
        .filter(Task.status == TaskStatus.AWAITING_APPROVAL, Task.created_at >= window_start, Task.created_at < window_end)
        .all()
    )
    lines = [f"Failed: {t.title} — {t.result_summary or 'no summary'}" for t in failed[:MAX_LISTED_ITEMS]]
    if len(failed) > MAX_LISTED_ITEMS:
        lines.append(f"...and {len(failed) - MAX_LISTED_ITEMS} more failed tasks")
    lines += [f"Awaiting approval: {t.title}" for t in awaiting]
    return lines


def _learning(session: Session, window_start: datetime, window_end: datetime) -> list[str]:
    reflections = (
        session.query(Reflection)
        .filter(
            Reflection.created_at >= window_start,
            Reflection.created_at < window_end,
            Reflection.become_long_term_knowledge.is_(True),
        )
        .all()
    )
    lines: list[str] = []
    for reflection in reflections:
        lines.extend(json.loads(reflection.should_change))
    return lines[:MAX_LISTED_ITEMS]


def _costs(metrics: AnalyticsReport) -> dict:
    return {
        "total_cost_usd": metrics.total_cost_usd,
        "total_tokens_input": metrics.total_tokens_input,
        "total_tokens_output": metrics.total_tokens_output,
        "cost_data_available": metrics.cost_data_available,
    }


def _workflow_evolution(session: Session) -> list[dict]:
    workflow_names = [row[0] for row in session.query(Strategy.workflow_name).distinct().all()]
    evolution = []
    for name in sorted(workflow_names):
        strategies = session.query(Strategy).filter_by(workflow_name=name).all()
        active = next((s for s in strategies if s.is_active), None)
        evolution.append(
            {
                "workflow_name": name,
                "version_count": len(strategies),
                "active_version": active.version if active else None,
                "active_success_rate": active.success_rate if active else None,
            }
        )
    return evolution


def _strategy_effectiveness(session: Session) -> list[dict]:
    active_strategies = session.query(Strategy).filter_by(is_active=True).all()
    return [
        {
            "workflow_name": s.workflow_name,
            "success_rate": s.success_rate,
            "sample_count": s.sample_count,
            "mean_duration_ms": s.mean_duration_ms,
        }
        for s in active_strategies
    ]


def _model_routing_summary(session: Session, window_start: datetime, window_end: datetime) -> dict:
    events = (
        session.query(Event)
        .filter(
            Event.event_type == "model_routing_decision",
            Event.created_at >= window_start,
            Event.created_at < window_end,
        )
        .all()
    )
    summary: dict[str, int] = {}
    for event in events:
        model = json.loads(event.payload_json)["chosen_model"]
        summary[model] = summary.get(model, 0) + 1
    return summary


def _experiments_summary(session: Session, window_start: datetime, window_end: datetime) -> list[dict]:
    experiments = (
        session.query(Experiment)
        .filter(Experiment.created_at >= window_start, Experiment.created_at < window_end)
        .all()
    )
    return [
        {
            "workflow_name": e.workflow_name,
            "hypothesis": e.hypothesis,
            "status": e.status.value,
            "recommendation": e.recommendation.value if e.recommendation else None,
        }
        for e in experiments
    ]


def _recommendations(session_factory: sessionmaker[Session], settings: Settings, window_days: int) -> list[str]:
    findings = find_bottlenecks(
        session_factory,
        window_days=window_days,
        min_samples=settings.bottleneck.min_samples,
        tool_failure_rate_threshold=settings.bottleneck.tool_failure_rate_threshold,
    )
    return [finding.detail for finding in findings]


def generate_hourly_review(
    session_factory: sessionmaker[Session], settings: Settings, now: datetime | None = None
) -> ReviewReport:
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(hours=settings.review.hourly_window_hours)
    window_end = now

    metrics = build_analytics_report(session_factory, window_start, window_end)
    session = session_factory()
    try:
        return ReviewReport(
            kind=ReviewKind.HOURLY.value,
            window_start=window_start,
            window_end=window_end,
            accomplishments=_accomplishments(session, window_start, window_end),
            blockers=_blockers(session, window_start, window_end),
            learning=_learning(session, window_start, window_end),
            costs=_costs(metrics),
            metrics=metrics,
        )
    finally:
        session.close()


def generate_weekly_review(
    session_factory: sessionmaker[Session], settings: Settings, now: datetime | None = None
) -> ReviewReport:
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=settings.review.weekly_window_days)
    window_end = now

    metrics = build_analytics_report(session_factory, window_start, window_end)
    session = session_factory()
    try:
        return ReviewReport(
            kind=ReviewKind.WEEKLY.value,
            window_start=window_start,
            window_end=window_end,
            accomplishments=_accomplishments(session, window_start, window_end),
            blockers=_blockers(session, window_start, window_end),
            learning=_learning(session, window_start, window_end),
            costs=_costs(metrics),
            metrics=metrics,
            workflow_evolution=_workflow_evolution(session),
            strategy_effectiveness=_strategy_effectiveness(session),
            model_routing_summary=_model_routing_summary(session, window_start, window_end),
            experiments_summary=_experiments_summary(session, window_start, window_end),
            recommendations=_recommendations(session_factory, settings, settings.review.weekly_window_days),
        )
    finally:
        session.close()


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {value!r}")


def persist_review(session_factory: sessionmaker[Session], report: ReviewReport) -> str:
    session = session_factory()
    try:
        review = Review(
            kind=ReviewKind(report.kind),
            window_start=report.window_start,
            window_end=report.window_end,
            report_json=json.dumps(dataclasses.asdict(report), default=_json_default),
        )
        session.add(review)
        session.commit()
        return review.id
    finally:
        session.close()
