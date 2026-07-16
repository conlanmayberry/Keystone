from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from megachud.api.schemas import PromotionDecisionRequest, PromotionSummary
from megachud.models.approval import ApprovalStatus
from megachud.models.promotion_request import PromotionRequest
from megachud.strategy.promotion import decide_promotion

router = APIRouter()


def _to_summary(request_row: PromotionRequest) -> PromotionSummary:
    return PromotionSummary(
        id=request_row.id,
        experiment_id=request_row.experiment_id,
        workflow_name=request_row.workflow_name,
        from_strategy_id=request_row.from_strategy_id,
        to_strategy_id=request_row.to_strategy_id,
        justification=request_row.justification,
        status=request_row.status.value,
        created_at=request_row.created_at.isoformat(),
    )


@router.get("/promotions", response_model=list[PromotionSummary])
def list_promotions(request: Request, status: str = "pending") -> list[PromotionSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        query = session.query(PromotionRequest)
        if status:
            query = query.filter_by(status=ApprovalStatus(status))
        requests = query.order_by(PromotionRequest.created_at.desc()).all()
        return [_to_summary(r) for r in requests]
    finally:
        session.close()


@router.post("/promotions/{promotion_request_id}/decision")
def decide(promotion_request_id: str, payload: PromotionDecisionRequest, request: Request) -> dict[str, bool]:
    session_factory = request.app.state.session_factory
    try:
        decide_promotion(
            session_factory,
            promotion_request_id,
            approved=payload.approved,
            note=payload.note,
            resolved_by="dashboard_user",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="promotion request not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    event_logger = request.app.state.event_logger
    event_logger.log(
        event_type="promotion_resolved",
        task_id=None,
        payload={"promotion_request_id": promotion_request_id, "approved": payload.approved},
    )

    return {"ok": True}
