from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from megachud.api.schemas import (
    StrategyCreateRequest,
    StrategyInvokeRequest,
    StrategyInvokeResponse,
    StrategySummary,
    StrategyUpdateRequest,
)
from megachud.models.strategy import Strategy
from megachud.strategy.invoker import StrategyParameterError, invoke_strategy

router = APIRouter()


def _to_summary(strategy: Strategy) -> StrategySummary:
    return StrategySummary(
        id=strategy.id,
        workflow_name=strategy.workflow_name,
        version=strategy.version,
        is_active=strategy.is_active,
        title=strategy.title,
        description=strategy.description,
        plan_template=json.loads(strategy.plan_template_json),
        parameters=json.loads(strategy.parameters_json),
        tags=json.loads(strategy.tags_json),
        origin=strategy.origin.value,
        sample_count=strategy.sample_count,
        success_count=strategy.success_count,
        success_rate=strategy.success_rate,
        mean_duration_ms=strategy.mean_duration_ms,
        mean_score=strategy.mean_score,
        created_at=strategy.created_at.isoformat(),
    )


@router.get("/strategies", response_model=list[StrategySummary])
def list_strategies(request: Request, workflow_name: str | None = None) -> list[StrategySummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        query = session.query(Strategy)
        if workflow_name:
            query = query.filter_by(workflow_name=workflow_name)
        strategies = query.order_by(Strategy.workflow_name, Strategy.version).all()
        return [_to_summary(s) for s in strategies]
    finally:
        session.close()


@router.get("/strategies/{strategy_id}", response_model=StrategySummary)
def get_strategy(strategy_id: str, request: Request) -> StrategySummary:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail="strategy not found")
        return _to_summary(strategy)
    finally:
        session.close()


@router.post("/strategies", response_model=StrategySummary)
def create_strategy(payload: StrategyCreateRequest, request: Request) -> StrategySummary:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        existing_versions = (
            session.query(Strategy).filter_by(workflow_name=payload.workflow_name).count()
        )
        strategy = Strategy(
            workflow_name=payload.workflow_name,
            version=existing_versions + 1,
            is_active=existing_versions == 0,
            title=payload.title,
            description=payload.description,
            plan_template_json=json.dumps(payload.plan_template),
            parameters_json=json.dumps(payload.parameters),
            tags_json=json.dumps(payload.tags),
        )
        session.add(strategy)
        session.commit()
        return _to_summary(strategy)
    finally:
        session.close()


@router.patch("/strategies/{strategy_id}", response_model=StrategySummary)
def update_strategy(strategy_id: str, payload: StrategyUpdateRequest, request: Request) -> StrategySummary:
    """Only permitted when is_active is False, so a live workflow version
    can't be edited out from under its own accruing metrics. This is what
    lets a human edit a freshly-cloned bottleneck challenger before/while
    it accrues experiment samples.
    """
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail="strategy not found")
        if strategy.is_active:
            raise HTTPException(status_code=409, detail="cannot edit the active strategy for a workflow")

        if payload.title is not None:
            strategy.title = payload.title
        if payload.description is not None:
            strategy.description = payload.description
        if payload.plan_template is not None:
            strategy.plan_template_json = json.dumps(payload.plan_template)
        if payload.parameters is not None:
            strategy.parameters_json = json.dumps(payload.parameters)
        if payload.tags is not None:
            strategy.tags_json = json.dumps(payload.tags)

        session.commit()
        return _to_summary(strategy)
    finally:
        session.close()


@router.post("/strategies/{strategy_id}/invoke", response_model=StrategyInvokeResponse)
def invoke(strategy_id: str, payload: StrategyInvokeRequest, request: Request) -> StrategyInvokeResponse:
    session_factory = request.app.state.session_factory
    try:
        task_id = invoke_strategy(session_factory, strategy_id, payload.params, title=payload.title)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="strategy not found") from exc
    except StrategyParameterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    event_logger = request.app.state.event_logger
    event_logger.log(
        event_type="strategy_invoked",
        task_id=task_id,
        payload={"strategy_id": strategy_id, "params": payload.params},
    )

    orchestrator = request.app.state.orchestrator
    request.app.state.executor.submit(orchestrator.run_task, task_id)

    return StrategyInvokeResponse(task_id=task_id)
