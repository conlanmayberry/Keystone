from __future__ import annotations

from megachud.events.logger import EventLogger
from megachud.models.event import Event
from megachud.routing.engine import RoutingDecision


def log_routing_decision(
    event_logger: EventLogger,
    task_id: str | None,
    task_type: str,
    decision: RoutingDecision,
) -> Event:
    """Logs a model_routing_decision Event through the existing single
    write path — no new table. task_id is None for dashboard-simulator
    calls with no real task; Event.task_id is already nullable.
    """
    return event_logger.log(
        event_type="model_routing_decision",
        task_id=task_id,
        payload={
            "task_type": task_type,
            "chosen_model": decision.chosen_model,
            "reason": decision.reason,
            "estimated_cost_usd": decision.estimated_cost_usd,
            "candidates_considered": decision.candidates_considered,
        },
    )
