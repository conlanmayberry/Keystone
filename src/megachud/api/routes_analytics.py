from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

from megachud.analytics.report import AnalyticsReport, build_analytics_report
from megachud.api.schemas import AnalyticsReportSummary

router = APIRouter()


def to_summary(report: AnalyticsReport) -> AnalyticsReportSummary:
    return AnalyticsReportSummary(
        window_start=report.window_start.isoformat(),
        window_end=report.window_end.isoformat(),
        task_counts_by_status=report.task_counts_by_status,
        tool_call_counts=report.tool_call_counts,
        tool_failure_rates=report.tool_failure_rates,
        event_counts_by_type=report.event_counts_by_type,
        strategy_success_rates=report.strategy_success_rates,
        experiment_outcome_counts=report.experiment_outcome_counts,
        become_long_term_knowledge_rate=report.become_long_term_knowledge_rate,
        total_cost_usd=report.total_cost_usd,
        total_tokens_input=report.total_tokens_input,
        total_tokens_output=report.total_tokens_output,
        cost_data_available=report.cost_data_available,
    )


@router.get("/analytics", response_model=AnalyticsReportSummary)
def get_analytics(request: Request, window_hours: int = 24) -> AnalyticsReportSummary:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)
    report = build_analytics_report(request.app.state.session_factory, window_start, now)
    return to_summary(report)
