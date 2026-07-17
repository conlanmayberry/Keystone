from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from megachud.models.event import Event
from megachud.models.experiment import Experiment
from megachud.models.reflection import Reflection
from megachud.models.strategy import Strategy
from megachud.models.task import Task


@dataclass
class AnalyticsReport:
    """Computed on demand, not persisted — same pattern as
    bottleneck.finder.BottleneckFinding (a cache-able query result, not a
    fact needing history)."""

    window_start: datetime
    window_end: datetime
    task_counts_by_status: dict[str, int] = field(default_factory=dict)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    tool_failure_rates: dict[str, float] = field(default_factory=dict)
    event_counts_by_type: dict[str, int] = field(default_factory=dict)
    strategy_success_rates: dict[str, float] = field(default_factory=dict)
    experiment_outcome_counts: dict[str, int] = field(default_factory=dict)
    become_long_term_knowledge_rate: float = 0.0
    total_cost_usd: float = 0.0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    cost_data_available: bool = False


def build_analytics_report(
    session_factory: sessionmaker[Session],
    window_start: datetime,
    window_end: datetime,
    agent_id: str | None = None,
) -> AnalyticsReport:
    """agent_id filters only task_counts_by_status and strategy_success_rates
    — the two stats with a direct agent_id column (Task, Strategy).
    tool_call_counts/tool_failure_rates/event_counts_by_type/cost and token
    totals are derived directly from Event rows with no join to Task, and
    Event is deliberately not one of the Phase 5 tagged tables — filtering
    those would need an Event.task_id -> Task.agent_id join, a schema/query
    change out of this phase's "structural readiness only" scope.
    experiment_outcome_counts/become_long_term_knowledge_rate stay
    unfiltered too (Experiment/Reflection aren't tagged). An honest gap,
    same pattern as cost_data_available.
    """
    session = session_factory()
    try:
        in_window = (Event.created_at >= window_start, Event.created_at < window_end)

        task_query = (
            session.query(Task.status, func.count())
            .filter(Task.created_at >= window_start, Task.created_at < window_end)
        )
        if agent_id:
            task_query = task_query.filter(Task.agent_id == agent_id)
        task_counts_by_status = {status.value: count for status, count in task_query.group_by(Task.status)}

        event_counts_by_type = dict(
            session.query(Event.event_type, func.count()).filter(*in_window).group_by(Event.event_type)
        )

        # payload_json's success flag needs Python-side parsing, so this one
        # can't be a pure SQL aggregate — but only tool_result rows and only
        # the two needed columns are loaded, not every event in the window.
        tool_outcomes: dict[str, list[bool]] = defaultdict(list)
        tool_result_rows = (
            session.query(Event.tool_name, Event.payload_json)
            .filter(Event.event_type == "tool_result", Event.tool_name.is_not(None), *in_window)
            .all()
        )
        for tool_name, payload_json in tool_result_rows:
            tool_outcomes[tool_name].append(bool(json.loads(payload_json).get("success")))
        tool_call_counts = {tool: len(outcomes) for tool, outcomes in tool_outcomes.items()}
        tool_failure_rates = {
            tool: 1 - (sum(outcomes) / len(outcomes)) for tool, outcomes in tool_outcomes.items()
        }

        strategy_query = session.query(Strategy).filter_by(is_active=True)
        if agent_id:
            strategy_query = strategy_query.filter(Strategy.agent_id == agent_id)
        active_strategies = strategy_query.all()
        strategy_success_rates = {s.workflow_name: s.success_rate for s in active_strategies}

        experiment_outcome_counts = {
            (recommendation.value if recommendation else "pending"): count
            for recommendation, count in (
                session.query(Experiment.recommendation, func.count())
                .filter(Experiment.created_at >= window_start, Experiment.created_at < window_end)
                .group_by(Experiment.recommendation)
            )
        }

        reflection_total, reflection_long_term = (
            session.query(
                func.count(),
                func.count().filter(Reflection.become_long_term_knowledge.is_(True)),
            )
            .filter(Reflection.created_at >= window_start, Reflection.created_at < window_end)
            .one()
        )
        become_long_term_knowledge_rate = (
            reflection_long_term / reflection_total if reflection_total else 0.0
        )

        cost_event_count, total_cost_usd, total_tokens_input, total_tokens_output = (
            session.query(
                func.count(Event.cost_usd),
                func.coalesce(func.sum(Event.cost_usd), 0.0),
                func.coalesce(func.sum(Event.tokens_input), 0),
                func.coalesce(func.sum(Event.tokens_output), 0),
            )
            .filter(*in_window)
            .one()
        )
        cost_data_available = cost_event_count > 0

        return AnalyticsReport(
            window_start=window_start,
            window_end=window_end,
            task_counts_by_status=task_counts_by_status,
            tool_call_counts=tool_call_counts,
            tool_failure_rates=tool_failure_rates,
            event_counts_by_type=event_counts_by_type,
            strategy_success_rates=strategy_success_rates,
            experiment_outcome_counts=experiment_outcome_counts,
            become_long_term_knowledge_rate=become_long_term_knowledge_rate,
            total_cost_usd=total_cost_usd,
            total_tokens_input=total_tokens_input,
            total_tokens_output=total_tokens_output,
            cost_data_available=cost_data_available,
        )
    finally:
        session.close()
