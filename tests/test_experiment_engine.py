from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.evaluation import Evaluation
from megachud.models.experiment import Experiment, ExperimentRecommendation, ExperimentStatus
from megachud.models.promotion_request import PromotionRequest
from megachud.models.strategy import Strategy
from megachud.models.task import Task, TaskStatus
from megachud.experiment.engine import evaluate_experiment


def create_strategy(session_factory, workflow_name="w", is_active=False) -> str:
    session = session_factory()
    try:
        strategy = Strategy(workflow_name=workflow_name, title="s", is_active=is_active)
        session.add(strategy)
        session.commit()
        return strategy.id
    finally:
        session.close()


def record_outcomes(session_factory, strategy_id: str, outcomes: list[bool]) -> None:
    logger = EventLogger(session_factory, EventBus())
    for success in outcomes:
        session = session_factory()
        try:
            started = datetime.now(timezone.utc) - timedelta(seconds=5)
            task = Task(
                title="t",
                prompt="p",
                status=TaskStatus.SUCCEEDED if success else TaskStatus.FAILED,
                started_at=started,
                completed_at=started + timedelta(seconds=1),
            )
            session.add(task)
            session.commit()
            task_id = task.id

            evaluation = Evaluation(task_id=task_id, success=success, checks_json="[]")
            session.add(evaluation)
            session.commit()
        finally:
            session.close()

        logger.log(event_type="strategy_invoked", task_id=task_id, payload={"strategy_id": strategy_id, "params": {}})


def create_experiment(session_factory, workflow_name, control_id, variant_id, min_samples=5) -> str:
    session = session_factory()
    try:
        experiment = Experiment(
            workflow_name=workflow_name,
            hypothesis="variant might do better",
            control_strategy_id=control_id,
            variant_strategy_id=variant_id,
            minimum_sample_size=min_samples,
        )
        session.add(experiment)
        session.commit()
        return experiment.id
    finally:
        session.close()


def test_insufficient_data_stays_running(session_factory):
    control_id = create_strategy(session_factory, "w", is_active=True)
    variant_id = create_strategy(session_factory, "w", is_active=False)
    record_outcomes(session_factory, control_id, [True, True])
    record_outcomes(session_factory, variant_id, [True])
    experiment_id = create_experiment(session_factory, "w", control_id, variant_id, min_samples=5)

    result = evaluate_experiment(session_factory, experiment_id)

    assert result.status == ExperimentStatus.RUNNING
    assert result.recommendation == ExperimentRecommendation.INSUFFICIENT_DATA


def test_variant_better_recommends_promotion_and_creates_request(session_factory):
    control_id = create_strategy(session_factory, "w", is_active=True)
    variant_id = create_strategy(session_factory, "w", is_active=False)
    record_outcomes(session_factory, control_id, [True, False, False, False, True])  # 40%
    record_outcomes(session_factory, variant_id, [True, True, True, True, False])  # 80%
    experiment_id = create_experiment(session_factory, "w", control_id, variant_id, min_samples=5)

    result = evaluate_experiment(session_factory, experiment_id)

    assert result.status == ExperimentStatus.CONCLUDED
    assert result.recommendation == ExperimentRecommendation.PROMOTE_VARIANT
    payload = json.loads(result.result_json)
    assert payload["success_rate_delta"] > 0

    session = session_factory()
    try:
        requests = session.query(PromotionRequest).filter_by(experiment_id=experiment_id).all()
        assert len(requests) == 1
        assert requests[0].to_strategy_id == variant_id
        assert requests[0].from_strategy_id == control_id
    finally:
        session.close()


def test_variant_worse_recommends_keep_control_no_request(session_factory):
    control_id = create_strategy(session_factory, "w", is_active=True)
    variant_id = create_strategy(session_factory, "w", is_active=False)
    record_outcomes(session_factory, control_id, [True, True, True, True, False])  # 80%
    record_outcomes(session_factory, variant_id, [True, False, False, False, True])  # 40%
    experiment_id = create_experiment(session_factory, "w", control_id, variant_id, min_samples=5)

    result = evaluate_experiment(session_factory, experiment_id)

    assert result.status == ExperimentStatus.CONCLUDED
    assert result.recommendation == ExperimentRecommendation.KEEP_CONTROL

    session = session_factory()
    try:
        requests = session.query(PromotionRequest).filter_by(experiment_id=experiment_id).all()
        assert requests == []
    finally:
        session.close()


def test_evaluate_experiment_can_be_called_repeatedly_while_accruing(session_factory):
    control_id = create_strategy(session_factory, "w", is_active=True)
    variant_id = create_strategy(session_factory, "w", is_active=False)
    record_outcomes(session_factory, control_id, [True])
    record_outcomes(session_factory, variant_id, [True])
    experiment_id = create_experiment(session_factory, "w", control_id, variant_id, min_samples=5)

    first = evaluate_experiment(session_factory, experiment_id)
    assert first.recommendation == ExperimentRecommendation.INSUFFICIENT_DATA

    record_outcomes(session_factory, control_id, [True, True, True, True])
    record_outcomes(session_factory, variant_id, [True, True, True, True])
    second = evaluate_experiment(session_factory, experiment_id)
    assert second.status == ExperimentStatus.CONCLUDED
