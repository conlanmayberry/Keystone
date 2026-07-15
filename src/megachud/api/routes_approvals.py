from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from megachud.api.schemas import ApprovalDecisionRequest, ApprovalSummary
from megachud.models.approval import ApprovalRequest, ApprovalStatus

router = APIRouter()


@router.get("/approvals", response_model=list[ApprovalSummary])
def list_approvals(request: Request, status: str = "pending") -> list[ApprovalSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        query = session.query(ApprovalRequest)
        if status:
            query = query.filter_by(status=ApprovalStatus(status))
        approvals = query.order_by(ApprovalRequest.created_at.desc()).all()
        return [
            ApprovalSummary(
                id=a.id,
                task_id=a.task_id,
                tool_name=a.tool_name,
                risk_level=a.risk_level.value,
                status=a.status.value,
                created_at=a.created_at.isoformat(),
                request_payload=json.loads(a.request_payload_json),
            )
            for a in approvals
        ]
    finally:
        session.close()


@router.post("/approvals/{approval_id}/decision")
def decide_approval(approval_id: str, payload: ApprovalDecisionRequest, request: Request) -> dict[str, bool]:
    approval_gate = request.app.state.approval_gate
    try:
        approval_gate.resolve(
            approval_id, approved=payload.approved, note=payload.note, resolved_by="dashboard_user"
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="approval request not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}
