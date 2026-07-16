from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from megachud.bottleneck.finder import find_bottlenecks, propose_experiment_from_bottleneck, BottleneckFinding
from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.evaluation import Evaluation
from megachud.models.experiment import Experiment, ExperimentStatus
from megachud.models.strategy import Strategy, StrategyOrigin
from megachud.models.task import Task, TaskStatus


def log_tool_result(session_factory, tool_name: str, success: bool) -> None:
    logger = EventLogger(session_factory, EventBus())
    logger.log(event_type="tool_result", tool_name=tool_name, payload={"success": success})


def test_tool_failure_rate_finding_detected_above_threshold(session_factory):
    for _ in range(3):
        log_tool_result(session_factory, "shell_exec", success=True)
    for _ in range(7):
        log_tool_result(session_factory, "shell_exec", success=False)  # 70% failure

    findings = find_bottlenecks(session_factory, min_samples=5, tool_failure_rate_threshold=0.2)

    matching = [f for f in findings if f.kind == "tool_failure_rate" and f.subject == "shell_exec"]
    assert len(matching) == 1
    assert matching[0].severity > 0.6


def test_tool_failure_rate_finding_skipped_below_min_samples(session_factory):
    for _ in range(2):
        log_tool_result(session_factory, "shell_exec", success=False)

    findings = find_bottlenecks(session_factory, min_samples=5, tool_failure_rate_threshold=0.2)

    assert not any(f.kind == "tool_failure_rate" for f in findings)


def test_tool_failure_rate_finding_skipped_below_threshold(session_factory):
    for _ in range(9):
        log_tool_result(session_factory, "write_file", success=True)
    log_tool_result(session_factory, "write_file", success=False)  # 10% failure, below 0.2 threshold

    findings = find_bottlenecks(session_factory, min_samples=5, tool_failure_rate_threshold=0.2)

    assert not any(f.kind == "tool_failure_rate" for f in findings)


def create_task_with_retries(session_factory, retry_count: int) -> str:
    session = session_factory()
    try:
        task = Task(title="t", prompt="p", retry_count=retry_count)
        session.add(task)
        session.commit()
        return task.id
    finally:
        session.close()


def test_high_retry_finding_detected(session_factory):
    for _ in range(4):
        create_task_with_retries(session_factory, retry_count=0)
    high_retry_task_id = create_task_with_retries(session_factory, retry_count=5)

    findings = find_bottlenecks(session_factory)

    matching = [f for f in findings if f.kind == "high_retry_tasks" and f.subject == high_retry_task_id]
    assert len(matching) == 1


def create_active_strategy(session_factory, workflow_name="w") -> str:
    session = session_factory()
    try:
        strategy = Strategy(workflow_name=workflow_name, title="s", is_active=True)
        session.add(strategy)
        session.commit()
        return strategy.id
    finally:
        session.close()


def record_strategy_outcomes(session_factory, strategy_id: str, outcomes: list[bool]) -> None:
    logger = EventLogger(session_factory, EventBus())
    for success in outcomes:
        session = session_factory()
        try:
            started = datetime.now(timezone.utc) - timedelta(seconds=5)
            task = Task(
                title="t", prompt="p",
                status=TaskStatus.SUCCEEDED if success else TaskStatus.FAILED,
                started_at=started, completed_at=started + timedelta(seconds=1),
            )
            session.add(task)
            session.commit()
            task_id = task.id
            session.add(Evaluation(task_id=task_id, success=success, checks_json="[]"))
            session.commit()
        finally:
            session.close()
        logger.log(event_type="strategy_invoked", task_id=task_id, payload={"strategy_id": strategy_id, "params": {}})


def test_declining_success_finding_detected(session_factory):
    strategy_id = create_active_strategy(session_factory, "declining_workflow")
    # First half: 5/5 success. Second half: 0/5 success. Decline = 1.0 > 0.15.
    record_strategy_outcomes(session_factory, strategy_id, [True] * 5 + [False] * 5)

    findings = find_bottlenecks(session_factory, min_samples=5)

    matching = [f for f in findings if f.kind == "strategy_declining_success" and f.subject == "declining_workflow"]
    assert len(matching) == 1


def test_declining_success_finding_not_triggered_when_stable(session_factory):
    strategy_id = create_active_strategy(session_factory, "stable_workflow")
    # Identical 3/5 success rate in both halves — no decline.
    stable_block = [True, True, False, False, True]
    record_strategy_outcomes(session_factory, strategy_id, stable_block + stable_block)

    findings = find_bottlenecks(session_factory, min_samples=5)

    assert not any(f.kind == "strategy_declining_success" and f.subject == "stable_workflow" for f in findings)


def test_findings_sorted_by_severity_descending(session_factory):
    for _ in range(2):
        log_tool_result(session_factory, "tool_a", success=True)
    for _ in range(8):
        log_tool_result(session_factory, "tool_a", success=False)  # 80% failure
    create_task_with_retries(session_factory, retry_count=3)
    for _ in range(4):
        create_task_with_retries(session_factory, retry_count=0)

    findings = find_bottlenecks(session_factory, min_samples=5)

    severities = [f.severity for f in findings]
    assert severities == sorted(severities, reverse=True)


def test_propose_experiment_from_bottleneck_creates_challenger_and_experiment(session_factory):
    active_id = create_active_strategy(session_factory, "declining_workflow")
    finding = BottleneckFinding(
        kind="strategy_declining_success", subject="declining_workflow", detail="dropped a lot", severity=0.9
    )

    experiment_id = propose_experiment_from_bottleneck(session_factory, finding, minimum_sample_size=5)

    assert experiment_id is not None
    session = session_factory()
    try:
        experiment = session.get(Experiment, experiment_id)
        assert experiment.control_strategy_id == active_id
        variant = session.get(Strategy, experiment.variant_strategy_id)
        assert variant.origin == StrategyOrigin.EXPERIMENT_VARIANT
        assert variant.parent_strategy_id == active_id
        assert variant.is_active is False
    finally:
        session.close()


def test_propose_experiment_from_bottleneck_ignores_other_finding_kinds(session_factory):
    finding = BottleneckFinding(kind="tool_failure_rate", subject="shell_exec", detail="d", severity=0.5)

    result = propose_experiment_from_bottleneck(session_factory, finding, minimum_sample_size=5)

    assert result is None


def test_propose_experiment_skips_if_running_experiment_already_exists(session_factory):
    create_active_strategy(session_factory, "declining_workflow")
    finding = BottleneckFinding(
        kind="strategy_declining_success", subject="declining_workflow", detail="d", severity=0.9
    )

    first = propose_experiment_from_bottleneck(session_factory, finding, minimum_sample_size=5)
    second = propose_experiment_from_bottleneck(session_factory, finding, minimum_sample_size=5)

    assert first is not None
    assert second is None
