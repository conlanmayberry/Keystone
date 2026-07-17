from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from megachud.api.schemas import ModelProfileSummary, RouteSimulateRequest, RoutingDecisionSummary
from megachud.routing.engine import NoQualifyingModelError
from megachud.routing.logging import log_routing_decision

router = APIRouter()


@router.get("/routing/profiles", response_model=list[ModelProfileSummary])
def list_profiles(request: Request) -> list[ModelProfileSummary]:
    profiles = request.app.state.settings.model_routing.profiles
    return [
        ModelProfileSummary(
            name=p.name,
            cost_per_1k_input_tokens=p.cost_per_1k_input_tokens,
            cost_per_1k_output_tokens=p.cost_per_1k_output_tokens,
            quality_tier=p.quality_tier,
            est_latency_ms=p.est_latency_ms,
        )
        for p in profiles
    ]


@router.post("/routing/simulate", response_model=RoutingDecisionSummary)
def simulate_route(payload: RouteSimulateRequest, request: Request) -> RoutingDecisionSummary:
    model_router = request.app.state.model_router
    try:
        decision = model_router.route(
            payload.task_type,
            payload.quality_target,
            est_tokens_input=payload.est_tokens_input,
            est_tokens_output=payload.est_tokens_output,
        )
    except NoQualifyingModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    log_routing_decision(
        request.app.state.event_logger, task_id=None, task_type=payload.task_type, decision=decision
    )

    return RoutingDecisionSummary(
        chosen_model=decision.chosen_model,
        reason=decision.reason,
        estimated_cost_usd=decision.estimated_cost_usd,
        candidates_considered=decision.candidates_considered,
    )
