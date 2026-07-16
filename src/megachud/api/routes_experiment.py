from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from megachud.api.schemas import ExperimentCreateRequest, ExperimentSummary
from megachud.experiment.engine import evaluate_experiment
from megachud.models.experiment import Experiment, ExperimentRecommendation
from megachud.models.promotion_request import PromotionRequest

router = APIRouter()


def _to_summary(experiment: Experiment) -> ExperimentSummary:
    return ExperimentSummary(
        id=experiment.id,
        workflow_name=experiment.workflow_name,
        hypothesis=experiment.hypothesis,
        control_strategy_id=experiment.control_strategy_id,
        variant_strategy_id=experiment.variant_strategy_id,
        minimum_sample_size=experiment.minimum_sample_size,
        status=experiment.status.value,
        recommendation=experiment.recommendation.value if experiment.recommendation else None,
        result=json.loads(experiment.result_json) if experiment.result_json else None,
        created_at=experiment.created_at.isoformat(),
    )


@router.get("/experiments", response_model=list[ExperimentSummary])
def list_experiments(request: Request, workflow_name: str | None = None, status: str | None = None) -> list[ExperimentSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        query = session.query(Experiment)
        if workflow_name:
            query = query.filter_by(workflow_name=workflow_name)
        if status:
            query = query.filter_by(status=status)
        experiments = query.order_by(Experiment.created_at.desc()).all()
        return [_to_summary(e) for e in experiments]
    finally:
        session.close()


@router.post("/experiments", response_model=ExperimentSummary)
def create_experiment(payload: ExperimentCreateRequest, request: Request) -> ExperimentSummary:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        experiment = Experiment(
            workflow_name=payload.workflow_name,
            hypothesis=payload.hypothesis,
            control_strategy_id=payload.control_strategy_id,
            variant_strategy_id=payload.variant_strategy_id,
            minimum_sample_size=payload.minimum_sample_size,
        )
        session.add(experiment)
        session.commit()
        return _to_summary(experiment)
    finally:
        session.close()


@router.post("/experiments/{experiment_id}/evaluate", response_model=ExperimentSummary)
def evaluate(experiment_id: str, request: Request) -> ExperimentSummary:
    session_factory = request.app.state.session_factory
    try:
        result = evaluate_experiment(session_factory, experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc

    if result.recommendation == ExperimentRecommendation.PROMOTE_VARIANT:
        session = session_factory()
        try:
            promotion = (
                session.query(PromotionRequest)
                .filter_by(experiment_id=experiment_id)
                .order_by(PromotionRequest.created_at.desc())
                .first()
            )
        finally:
            session.close()
        if promotion is not None:
            event_logger = request.app.state.event_logger
            event_logger.log(
                event_type="promotion_requested",
                task_id=None,
                payload={"promotion_request_id": promotion.id, "experiment_id": experiment_id},
            )

    return _to_summary(result)
