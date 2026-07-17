from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

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
    session_factory: sessionmaker[Session], window_start: datetime, window_end: datetime
) -> AnalyticsReport:
    session = session_factory()
    try:
        tasks = (
            session.query(Task)
            .filter(Task.created_at >= window_start, Task.created_at < window_end)
            .all()
        )
        task_counts_by_status = dict(Counter(t.status.value for t in tasks))

        all_events = (
            session.query(Event)
            .filter(Event.created_at >= window_start, Event.created_at < window_end)
            .all()
        )
        event_counts_by_type = dict(Counter(e.event_type for e in all_events))

        tool_outcomes: dict[str, list[bool]] = defaultdict(list)
        for event in all_events:
            if event.event_type != "tool_result" or event.tool_name is None:
                continue
            payload = json.loads(event.payload_json)
            tool_outcomes[event.tool_name].append(bool(payload.get("success")))
        tool_call_counts = {tool: len(outcomes) for tool, outcomes in tool_outcomes.items()}
        tool_failure_rates = {
            tool: 1 - (sum(outcomes) / len(outcomes)) for tool, outcomes in tool_outcomes.items()
        }

        active_strategies = session.query(Strategy).filter_by(is_active=True).all()
        strategy_success_rates = {s.workflow_name: s.success_rate for s in active_strategies}

        experiments = (
            session.query(Experiment)
            .filter(Experiment.created_at >= window_start, Experiment.created_at < window_end)
            .all()
        )
        experiment_outcome_counts = dict(
            Counter(e.recommendation.value if e.recommendation else "pending" for e in experiments)
        )

        reflections = (
            session.query(Reflection)
            .filter(Reflection.created_at >= window_start, Reflection.created_at < window_end)
            .all()
        )
        become_long_term_knowledge_rate = (
            sum(1 for r in reflections if r.become_long_term_knowledge) / len(reflections)
            if reflections
            else 0.0
        )

        cost_events = [e for e in all_events if e.cost_usd is not None]
        total_cost_usd = sum(e.cost_usd for e in cost_events)
        total_tokens_input = sum(e.tokens_input or 0 for e in all_events)
        total_tokens_output = sum(e.tokens_output or 0 for e in all_events)
        cost_data_available = len(cost_events) > 0

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
