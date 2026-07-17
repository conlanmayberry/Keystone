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
    # contains() is a cheap SQL-side prefilter (a UUID has no LIKE
    # wildcards); json.loads below stays the authoritative check, so a
    # payload merely mentioning the id elsewhere can't slip through.
    invoked_events = (
        session.query(Event.task_id, Event.payload_json)
        .filter_by(event_type="strategy_invoked")
        .filter(Event.payload_json.contains(strategy_id))
        .order_by(Event.id)
        .all()
    )
    task_ids = [
        task_id
        for task_id, payload_json in invoked_events
        if json.loads(payload_json).get("strategy_id") == strategy_id
    ]
    if not task_ids:
        return []

    tasks_by_id = {t.id: t for t in session.query(Task).filter(Task.id.in_(set(task_ids)))}
    # Ascending by id + last-write-wins == latest evaluation per task, in
    # two batched queries instead of 2 queries per task.
    latest_evaluation_by_task: dict[str, Evaluation] = {}
    for evaluation in (
        session.query(Evaluation).filter(Evaluation.task_id.in_(set(task_ids))).order_by(Evaluation.id)
    ):
        latest_evaluation_by_task[evaluation.task_id] = evaluation

    outcomes: list[dict] = []
    for task_id in task_ids:
        task = tasks_by_id.get(task_id)
        if task is None or task.status.value not in ("succeeded", "failed"):
            continue
        evaluation = latest_evaluation_by_task.get(task_id)
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
            # mean_cost_usd intentionally left at 0.0 — llm_call events now
            # carry real Event.cost_usd, but none of those calls are
            # attributable to a strategy invocation yet; do not fabricate
            # cost data.

            session.commit()
        finally:
            session.close()
