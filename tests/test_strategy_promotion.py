from __future__ import annotations

import json

import pytest

from megachud.models.approval import ApprovalStatus
from megachud.models.experiment import Experiment, ExperimentRecommendation
from megachud.models.promotion_request import PromotionRequest
from megachud.models.strategy import Strategy, StrategyOrigin
from megachud.strategy.promotion import decide_promotion, propose_promotion


def create_active_strategy(session_factory, workflow_name="w") -> str:
    session = session_factory()
    try:
        strategy = Strategy(workflow_name=workflow_name, title="control", is_active=True)
        session.add(strategy)
        session.commit()
        return strategy.id
    finally:
        session.close()


def create_variant(session_factory, workflow_name, parent_id) -> str:
    session = session_factory()
    try:
        strategy = Strategy(
            workflow_name=workflow_name,
            title="variant",
            is_active=False,
            origin=StrategyOrigin.EXPERIMENT_VARIANT,
            parent_strategy_id=parent_id,
        )
        session.add(strategy)
        session.commit()
        return strategy.id
    finally:
        session.close()


def create_concluded_experiment(session_factory, workflow_name, control_id, variant_id, recommendation):
    session = session_factory()
    try:
        experiment = Experiment(
            workflow_name=workflow_name,
            hypothesis="h",
            control_strategy_id=control_id,
            variant_strategy_id=variant_id,
            recommendation=recommendation,
            result_json=json.dumps({"success_rate_delta": 0.2, "variant": {"n": 12}}),
        )
        session.add(experiment)
        session.commit()
        return experiment.id
    finally:
        session.close()


def test_propose_promotion_creates_request(session_factory):
    control_id = create_active_strategy(session_factory, "w")
    variant_id = create_variant(session_factory, "w", control_id)
    experiment_id = create_concluded_experiment(
        session_factory, "w", control_id, variant_id, ExperimentRecommendation.PROMOTE_VARIANT
    )

    request_id = propose_promotion(session_factory, experiment_id)

    session = session_factory()
    try:
        request = session.get(PromotionRequest, request_id)
        assert request.from_strategy_id == control_id
        assert request.to_strategy_id == variant_id
        assert request.status == ApprovalStatus.PENDING
        assert "success_rate_delta" in request.justification
    finally:
        session.close()


def test_propose_promotion_rejects_non_promote_recommendation(session_factory):
    control_id = create_active_strategy(session_factory, "w")
    variant_id = create_variant(session_factory, "w", control_id)
    experiment_id = create_concluded_experiment(
        session_factory, "w", control_id, variant_id, ExperimentRecommendation.KEEP_CONTROL
    )

    with pytest.raises(ValueError):
        propose_promotion(session_factory, experiment_id)


def test_decide_promotion_approved_flips_is_active_atomically(session_factory):
    control_id = create_active_strategy(session_factory, "w")
    variant_id = create_variant(session_factory, "w", control_id)
    experiment_id = create_concluded_experiment(
        session_factory, "w", control_id, variant_id, ExperimentRecommendation.PROMOTE_VARIANT
    )
    request_id = propose_promotion(session_factory, experiment_id)

    decide_promotion(session_factory, request_id, approved=True, note="looks good", resolved_by="tester")

    session = session_factory()
    try:
        control = session.get(Strategy, control_id)
        variant = session.get(Strategy, variant_id)
        request = session.get(PromotionRequest, request_id)
        assert control.is_active is False
        assert variant.is_active is True
        assert request.status == ApprovalStatus.APPROVED
        assert request.resolved_by == "tester"
    finally:
        session.close()


def test_decide_promotion_denied_leaves_strategies_unchanged(session_factory):
    control_id = create_active_strategy(session_factory, "w")
    variant_id = create_variant(session_factory, "w", control_id)
    experiment_id = create_concluded_experiment(
        session_factory, "w", control_id, variant_id, ExperimentRecommendation.PROMOTE_VARIANT
    )
    request_id = propose_promotion(session_factory, experiment_id)

    decide_promotion(session_factory, request_id, approved=False, note="not yet", resolved_by="tester")

    session = session_factory()
    try:
        control = session.get(Strategy, control_id)
        variant = session.get(Strategy, variant_id)
        request = session.get(PromotionRequest, request_id)
        assert control.is_active is True
        assert variant.is_active is False
        assert request.status == ApprovalStatus.DENIED
    finally:
        session.close()


def test_decide_promotion_already_resolved_raises(session_factory):
    control_id = create_active_strategy(session_factory, "w")
    variant_id = create_variant(session_factory, "w", control_id)
    experiment_id = create_concluded_experiment(
        session_factory, "w", control_id, variant_id, ExperimentRecommendation.PROMOTE_VARIANT
    )
    request_id = propose_promotion(session_factory, experiment_id)
    decide_promotion(session_factory, request_id, approved=True, note=None, resolved_by="tester")

    with pytest.raises(ValueError):
        decide_promotion(session_factory, request_id, approved=True, note=None, resolved_by="tester")
