from __future__ import annotations

import json

from sqlalchemy.orm import Session, sessionmaker

from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.strategy import Strategy
from megachud.models.task import Task


def outcomes_for_strategy(session: Session, strategy_id: str) -> list[dict]:
    """Every completed Task invoked from strategy_id (found via its
    'strategy_invoked' Event), joined to that task's latest Evaluation and
    duration. Explicitly ORDER BY Event.id — chronological order matters
    for bottleneck/finder.py's first-half-vs-second-half comparison, so
    this must not rely on incidental SQLite rowid ordering. Shared by
    StrategyMetricsHandler, experiment/engine.py, and bottleneck/finder.py
    so this join is written exactly once.
    """
    invoked_events = (
        session.query(Event)
        .filter_by(event_type="strategy_invoked")
        .order_by(Event.id)
        .all()
    )
    task_ids = [e.task_id for e in invoked_events if json.loads(e.payload_json).get("strategy_id") == strategy_id]

    outcomes: list[dict] = []
    for task_id in task_ids:
        task = session.get(Task, task_id)
        if task is None or task.status.value not in ("succeeded", "failed"):
            continue
        evaluation = session.query(Evaluation).filter_by(task_id=task_id).order_by(Evaluation.id.desc()).first()
        duration_ms = (
            int((task.completed_at - task.started_at).total_seconds() * 1000)
            if task.started_at and task.completed_at
            else 0
        )
        outcomes.append(
            {
                "task_id": task_id,
                "success": bool(evaluation and evaluation.success),
                "duration_ms": duration_ms,
                "score": evaluation.score if evaluation else None,
            }
        )
    return outcomes


class StrategyMetricsHandler:
    """Wired into EventDispatcher alongside TaskCompletionHandler. On every
    task_completed/task_failed, checks whether the task carries a
    strategy_invoked event; a no-op if not (the overwhelming majority of
    tasks). Otherwise updates that Strategy's rolling metrics
    incrementally.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __call__(self, event: Event) -> None:
        if event.event_type not in ("task_completed", "task_failed") or event.task_id is None:
            return

        session = self._session_factory()
        try:
            invoked = (
                session.query(Event)
                .filter_by(task_id=event.task_id, event_type="strategy_invoked")
                .order_by(Event.id.desc())
                .first()
            )
            if invoked is None:
                return

            strategy_id = json.loads(invoked.payload_json)["strategy_id"]
            strategy = session.get(Strategy, strategy_id)
            task = session.get(Task, event.task_id)
            evaluation = (
                session.query(Evaluation).filter_by(task_id=event.task_id).order_by(Evaluation.id.desc()).first()
            )

            success = bool(evaluation and evaluation.success)
            duration_ms = (
                int((task.completed_at - task.started_at).total_seconds() * 1000)
                if task.started_at and task.completed_at
                else 0
            )

            n = strategy.sample_count
            strategy.sample_count = n + 1
            strategy.success_count += 1 if success else 0
            strategy.mean_duration_ms = (strategy.mean_duration_ms * n + duration_ms) / (n + 1)
            if evaluation is not None and evaluation.score is not None:
                # Dead code this phase: EvaluationEngine never populates
                # Evaluation.score yet, so this branch never fires. Kept
                # honest and ready for the day a future evaluator does.
                prior_n = n if strategy.mean_score is not None else 0
                prior = strategy.mean_score or 0.0
                strategy.mean_score = (prior * prior_n + evaluation.score) / (prior_n + 1)
            # mean_cost_usd intentionally left at 0.0 — no cost tracking
            # exists anywhere in the codebase yet (Event.cost_usd unused
            # since Phase 1); do not fabricate cost data.

            session.commit()
        finally:
            session.close()
