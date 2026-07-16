from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from megachud.models.approval import ApprovalStatus
from megachud.models.experiment import Experiment, ExperimentRecommendation
from megachud.models.promotion_request import PromotionRequest
from megachud.models.strategy import Strategy


def propose_promotion(session_factory: sessionmaker[Session], experiment_id: str) -> str:
    """Called once an Experiment concludes with recommendation ==
    PROMOTE_VARIANT. Creates a PromotionRequest row. Raises if the
    experiment's recommendation isn't PROMOTE_VARIANT — defensive, should
    only be called from that branch.
    """
    session = session_factory()
    try:
        experiment = session.get(Experiment, experiment_id)
        if experiment.recommendation != ExperimentRecommendation.PROMOTE_VARIANT:
            raise ValueError("can only propose promotion for a PROMOTE_VARIANT experiment")

        active = (
            session.query(Strategy)
            .filter_by(workflow_name=experiment.workflow_name, is_active=True)
            .first()
        )
        result = json.loads(experiment.result_json or "{}")
        request = PromotionRequest(
            experiment_id=experiment.id,
            workflow_name=experiment.workflow_name,
            from_strategy_id=active.id if active else experiment.control_strategy_id,
            to_strategy_id=experiment.variant_strategy_id,
            justification=(
                f"success_rate_delta={result.get('success_rate_delta', 0):.3f} over "
                f"{result.get('variant', {}).get('n', 0)} variant samples"
            ),
        )
        session.add(request)
        session.commit()
        return request.id
    finally:
        session.close()


def decide_promotion(
    session_factory: sessionmaker[Session],
    promotion_request_id: str,
    approved: bool,
    note: str | None,
    resolved_by: str,
) -> None:
    """Immediate, non-blocking decision — unlike ApprovalGate, no polling
    involved. If approved: flips is_active atomically (old active Strategy
    for workflow_name -> False, target Strategy -> True) in the same
    transaction as marking the PromotionRequest APPROVED. If denied: only
    the PromotionRequest status changes.
    """
    session = session_factory()
    try:
        request = session.get(PromotionRequest, promotion_request_id)
        if request is None:
            raise KeyError(f"unknown promotion request: {promotion_request_id!r}")
        if request.status != ApprovalStatus.PENDING:
            raise ValueError(f"promotion request already resolved: {request.status.value}")

        request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        request.resolved_at = datetime.now(timezone.utc)
        request.resolved_by = resolved_by
        request.decision_note = note

        if approved:
            old_active = (
                session.query(Strategy)
                .filter_by(workflow_name=request.workflow_name, is_active=True)
                .first()
            )
            if old_active is not None:
                old_active.is_active = False
            new_active = session.get(Strategy, request.to_strategy_id)
            new_active.is_active = True

        session.commit()
    finally:
        session.close()
