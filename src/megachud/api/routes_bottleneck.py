from __future__ import annotations

from fastapi import APIRouter, Request

from megachud.api.schemas import BottleneckFindingSummary, ProposeExperimentRequest
from megachud.bottleneck.finder import BottleneckFinding, find_bottlenecks, propose_experiment_from_bottleneck

router = APIRouter()


@router.get("/bottlenecks", response_model=list[BottleneckFindingSummary])
def list_bottlenecks(request: Request, window_days: int | None = None) -> list[BottleneckFindingSummary]:
    settings = request.app.state.settings
    findings = find_bottlenecks(
        request.app.state.session_factory,
        window_days=window_days if window_days is not None else settings.bottleneck.window_days,
        min_samples=settings.bottleneck.min_samples,
        tool_failure_rate_threshold=settings.bottleneck.tool_failure_rate_threshold,
    )
    return [
        BottleneckFindingSummary(kind=f.kind, subject=f.subject, detail=f.detail, severity=f.severity)
        for f in findings
    ]


@router.post("/bottlenecks/propose_experiment")
def propose_experiment(payload: ProposeExperimentRequest, request: Request) -> dict[str, str | None]:
    settings = request.app.state.settings
    finding = BottleneckFinding(
        kind=payload.kind, subject=payload.subject, detail=payload.detail, severity=payload.severity
    )
    experiment_id = propose_experiment_from_bottleneck(
        request.app.state.session_factory, finding, settings.experiment.default_minimum_sample_size
    )
    return {"experiment_id": experiment_id}
