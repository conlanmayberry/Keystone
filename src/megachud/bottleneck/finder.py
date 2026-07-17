from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from megachud.models.event import Event
from megachud.models.experiment import Experiment, ExperimentStatus
from megachud.models.strategy import Strategy, StrategyOrigin
from megachud.models.task import Task
from megachud.strategy.metrics import outcomes_for_strategy


@dataclass
class BottleneckFinding:
    kind: str  # "tool_failure_rate" | "strategy_declining_success" | "high_retry_tasks"
    subject: str  # tool_name, or workflow_name, or task_id
    detail: str
    severity: float  # 0..1, higher = worse


def find_bottlenecks(
    session_factory: sessionmaker[Session],
    window_days: int = 7,
    min_samples: int = 5,
    tool_failure_rate_threshold: float = 0.2,
) -> list[BottleneckFinding]:
    """Three deterministic aggregation queries over existing tables — no
    new persisted state (a BottleneckFinding is a cache-able query result,
    not a fact needing history).
    """
    session = session_factory()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        findings: list[BottleneckFinding] = []
        findings.extend(_tool_failure_rate_findings(session, since, min_samples, tool_failure_rate_threshold))
        findings.extend(_high_retry_findings(session, since))
        findings.extend(_declining_success_findings(session, min_samples))
        return sorted(findings, key=lambda f: -f.severity)
    finally:
        session.close()


def _tool_failure_rate_findings(session: Session, since: datetime, min_samples: int, threshold: float) -> list[BottleneckFinding]:
    results = (
        session.query(Event.tool_name, Event.payload_json)
        .filter(Event.event_type == "tool_result", Event.tool_name.is_not(None), Event.created_at >= since)
        .all()
    )
    by_tool: dict[str, list[bool]] = {}
    for tool_name, payload_json in results:
        by_tool.setdefault(tool_name, []).append(bool(json.loads(payload_json).get("success")))

    findings: list[BottleneckFinding] = []
    for tool_name, outcomes in by_tool.items():
        if len(outcomes) < min_samples:
            continue
        failure_rate = 1 - (sum(outcomes) / len(outcomes))
        if failure_rate > threshold:
            findings.append(
                BottleneckFinding(
                    kind="tool_failure_rate",
                    subject=tool_name,
                    detail=f"{tool_name} failed {failure_rate:.0%} of {len(outcomes)} calls in the last {(datetime.now(timezone.utc) - since).days}d",
                    severity=failure_rate,
                )
            )
    return findings


def _high_retry_findings(session: Session, since: datetime) -> list[BottleneckFinding]:
    avg_retries = session.query(func.avg(Task.retry_count)).filter(Task.created_at >= since).scalar() or 0.0
    high_retry = (
        session.query(Task)
        .filter(Task.created_at >= since, Task.retry_count > max(avg_retries * 2, 1))
        .all()
    )
    return [
        BottleneckFinding(
            kind="high_retry_tasks",
            subject=task.id,
            detail=f"task {task.id!r} ({task.title}) retried {task.retry_count} times vs avg {avg_retries:.1f}",
            severity=min(task.retry_count / 5, 1.0),
        )
        for task in high_retry
    ]


def _declining_success_findings(session: Session, min_samples: int) -> list[BottleneckFinding]:
    active_strategies = session.query(Strategy).filter_by(is_active=True).all()
    findings: list[BottleneckFinding] = []
    for strategy in active_strategies:
        outcomes = outcomes_for_strategy(session, strategy.id)
        if len(outcomes) < min_samples * 2:
            continue
        mid = len(outcomes) // 2
        first_rate = sum(o["success"] for o in outcomes[:mid]) / mid
        second_rate = sum(o["success"] for o in outcomes[mid:]) / (len(outcomes) - mid)
        decline = first_rate - second_rate
        if decline > 0.15:
            findings.append(
                BottleneckFinding(
                    kind="strategy_declining_success",
                    subject=strategy.workflow_name,
                    detail=(
                        f"{strategy.workflow_name} success rate dropped from {first_rate:.0%} to "
                        f"{second_rate:.0%} over {len(outcomes)} samples"
                    ),
                    severity=decline,
                )
            )
    return findings


def propose_experiment_from_bottleneck(
    session_factory: sessionmaker[Session],
    finding: BottleneckFinding,
    minimum_sample_size: int,
) -> str | None:
    """Only acts on kind == 'strategy_declining_success'. Skips (returns
    None) if a RUNNING Experiment already exists for that workflow.
    Otherwise clones the active Strategy into a new challenger
    (origin=EXPERIMENT_VARIANT) with IDENTICAL plan_template_json — Phase 3
    does not auto-mutate plans, that needs judgment/LLM and is out of
    scope. The human is expected to edit the challenger's plan via
    PATCH /strategies/{id} before/while it accrues samples.
    """
    if finding.kind != "strategy_declining_success":
        return None

    session = session_factory()
    try:
        workflow_name = finding.subject

        existing_running = (
            session.query(Experiment)
            .filter_by(workflow_name=workflow_name, status=ExperimentStatus.RUNNING)
            .first()
        )
        if existing_running is not None:
            return None

        active = session.query(Strategy).filter_by(workflow_name=workflow_name, is_active=True).first()
        if active is None:
            return None

        next_version = (
            session.query(func.max(Strategy.version)).filter_by(workflow_name=workflow_name).scalar() or 0
        ) + 1
        challenger = Strategy(
            workflow_name=workflow_name,
            version=next_version,
            is_active=False,
            title=f"{active.title} (challenger v{next_version})",
            description=active.description,
            plan_template_json=active.plan_template_json,
            parameters_json=active.parameters_json,
            tags_json=active.tags_json,
            origin=StrategyOrigin.EXPERIMENT_VARIANT,
            parent_strategy_id=active.id,
        )
        session.add(challenger)
        session.commit()

        experiment = Experiment(
            workflow_name=workflow_name,
            hypothesis=finding.detail,
            control_strategy_id=active.id,
            variant_strategy_id=challenger.id,
            minimum_sample_size=minimum_sample_size,
        )
        session.add(experiment)
        session.commit()
        return experiment.id
    finally:
        session.close()
