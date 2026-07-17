from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from megachud.api.routes_analytics import to_summary as metrics_to_summary
from megachud.api.schemas import ReviewReportSummary, ReviewSummary
from megachud.models.review import Review, ReviewKind
from megachud.review.generator import ReviewReport, generate_hourly_review, generate_weekly_review, persist_review

router = APIRouter()


def _parse_kind(kind: str) -> ReviewKind:
    try:
        return ReviewKind(kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"unknown review kind: {kind!r}") from exc


def _generate(kind: ReviewKind, session_factory, settings) -> ReviewReport:
    if kind == ReviewKind.HOURLY:
        return generate_hourly_review(session_factory, settings)
    return generate_weekly_review(session_factory, settings)


def _to_summary(report: ReviewReport) -> ReviewReportSummary:
    return ReviewReportSummary(
        kind=report.kind,
        window_start=report.window_start.isoformat(),
        window_end=report.window_end.isoformat(),
        accomplishments=report.accomplishments,
        blockers=report.blockers,
        learning=report.learning,
        costs=report.costs,
        metrics=metrics_to_summary(report.metrics),
        workflow_evolution=report.workflow_evolution,
        strategy_effectiveness=report.strategy_effectiveness,
        model_routing_summary=report.model_routing_summary,
        experiments_summary=report.experiments_summary,
        recommendations=report.recommendations,
    )


@router.get("/reviews/{kind}/preview", response_model=ReviewReportSummary)
def preview_review(kind: str, request: Request) -> ReviewReportSummary:
    """Computes only — does not persist. Lets the dashboard show a live
    preview without cluttering review history."""
    review_kind = _parse_kind(kind)
    report = _generate(review_kind, request.app.state.session_factory, request.app.state.settings)
    return _to_summary(report)


@router.post("/reviews/{kind}/generate", response_model=ReviewReportSummary)
def generate_review(kind: str, request: Request) -> ReviewReportSummary:
    """Computes AND persists."""
    review_kind = _parse_kind(kind)
    report = _generate(review_kind, request.app.state.session_factory, request.app.state.settings)
    persist_review(
        request.app.state.session_factory,
        report,
        agent_id=request.app.state.current_agent_id,
        project_name=request.app.state.settings.project_name,
    )
    return _to_summary(report)


@router.get("/reviews", response_model=list[ReviewSummary])
def list_reviews(request: Request, kind: str | None = None, agent_id: str | None = None) -> list[ReviewSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        query = session.query(Review)
        if kind:
            query = query.filter_by(kind=_parse_kind(kind))
        if agent_id:
            query = query.filter_by(agent_id=agent_id)
        reviews = query.order_by(Review.created_at.desc()).all()
        return [
            ReviewSummary(
                id=r.id,
                kind=r.kind.value,
                window_start=r.window_start.isoformat(),
                window_end=r.window_end.isoformat(),
                created_at=r.created_at.isoformat(),
            )
            for r in reviews
        ]
    finally:
        session.close()
