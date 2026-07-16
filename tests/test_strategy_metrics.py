from __future__ import annotations

import json

from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.evaluation import Evaluation
from megachud.models.strategy import Strategy
from megachud.models.task import Task, TaskStatus
from megachud.strategy.metrics import StrategyMetricsHandler, outcomes_for_strategy


def create_strategy(session_factory) -> str:
    session = session_factory()
    try:
        strategy = Strategy(workflow_name="w", title="t", is_active=True)
        session.add(strategy)
        session.commit()
        return strategy.id
    finally:
        session.close()


def create_completed_task(session_factory, success: bool, started_offset_seconds=0):
    from datetime import datetime, timedelta, timezone

    session = session_factory()
    try:
        started = datetime.now(timezone.utc) - timedelta(seconds=10)
        task = Task(
            title="t",
            prompt="p",
            status=TaskStatus.SUCCEEDED if success else TaskStatus.FAILED,
            started_at=started,
            completed_at=started + timedelta(seconds=2),
        )
        session.add(task)
        session.commit()
        task_id = task.id

        evaluation = Evaluation(task_id=task_id, success=success, checks_json="[]")
        session.add(evaluation)
        session.commit()
        return task_id
    finally:
        session.close()


def test_task_without_strategy_invoked_event_is_noop(session_factory):
    handler = StrategyMetricsHandler(session_factory)
    task_id = create_completed_task(session_factory, success=True)
    logger = EventLogger(session_factory, EventBus(), on_event=handler)

    # Should not raise even though this task has no strategy_invoked event.
    logger.log(event_type="task_completed", task_id=task_id, payload={})


def test_task_completion_updates_strategy_metrics(session_factory):
    strategy_id = create_strategy(session_factory)
    task_id = create_completed_task(session_factory, success=True)

    logger = EventLogger(session_factory, EventBus())
    logger.log(event_type="strategy_invoked", task_id=task_id, payload={"strategy_id": strategy_id, "params": {}})

    handler = StrategyMetricsHandler(session_factory)
    dispatch_logger = EventLogger(session_factory, EventBus(), on_event=handler)
    dispatch_logger.log(event_type="task_completed", task_id=task_id, payload={})

    session = session_factory()
    try:
        strategy = session.get(Strategy, strategy_id)
        assert strategy.sample_count == 1
        assert strategy.success_count == 1
        assert strategy.mean_duration_ms > 0
    finally:
        session.close()


def test_multiple_outcomes_average_correctly(session_factory):
    strategy_id = create_strategy(session_factory)
    handler = StrategyMetricsHandler(session_factory)
    dispatch_logger = EventLogger(session_factory, EventBus(), on_event=handler)
    plain_logger = EventLogger(session_factory, EventBus())

    for success in (True, False, True):
        task_id = create_completed_task(session_factory, success=success)
        plain_logger.log(event_type="strategy_invoked", task_id=task_id, payload={"strategy_id": strategy_id, "params": {}})
        dispatch_logger.log(event_type="task_completed" if success else "task_failed", task_id=task_id, payload={})

    session = session_factory()
    try:
        strategy = session.get(Strategy, strategy_id)
        assert strategy.sample_count == 3
        assert strategy.success_count == 2
        assert strategy.success_rate == 2 / 3
    finally:
        session.close()


def test_outcomes_for_strategy_is_chronologically_ordered(session_factory):
    strategy_id = create_strategy(session_factory)
    plain_logger = EventLogger(session_factory, EventBus())
    task_ids = []
    for success in (True, False, True, True):
        task_id = create_completed_task(session_factory, success=success)
        plain_logger.log(event_type="strategy_invoked", task_id=task_id, payload={"strategy_id": strategy_id, "params": {}})
        task_ids.append(task_id)

    session = session_factory()
    try:
        outcomes = outcomes_for_strategy(session, strategy_id)
    finally:
        session.close()

    assert [o["task_id"] for o in outcomes] == task_ids
