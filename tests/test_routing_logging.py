from __future__ import annotations

import json

from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.event import Event
from megachud.routing.engine import RoutingDecision
from megachud.routing.logging import log_routing_decision


def test_log_routing_decision_persists_event(session_factory):
    event_logger = EventLogger(session_factory, EventBus())
    decision = RoutingDecision(
        chosen_model="balanced",
        reason="cheapest profile meeting quality_target=2",
        estimated_cost_usd=0.0018,
        candidates_considered=["balanced", "premium"],
    )

    event = log_routing_decision(event_logger, task_id=None, task_type="summarize", decision=decision)

    assert event.event_type == "model_routing_decision"
    assert event.task_id is None

    session = session_factory()
    try:
        fetched = session.get(Event, event.id)
        payload = json.loads(fetched.payload_json)
        assert payload["task_type"] == "summarize"
        assert payload["chosen_model"] == "balanced"
        assert payload["estimated_cost_usd"] == 0.0018
        assert payload["candidates_considered"] == ["balanced", "premium"]
    finally:
        session.close()


def test_log_routing_decision_with_real_task_id(session_factory):
    from megachud.models.task import Task

    session = session_factory()
    try:
        task = Task(title="t", prompt="p")
        session.add(task)
        session.commit()
        task_id = task.id
    finally:
        session.close()

    event_logger = EventLogger(session_factory, EventBus())
    decision = RoutingDecision(chosen_model="fast-cheap", reason="r", estimated_cost_usd=0.0, candidates_considered=["fast-cheap"])

    event = log_routing_decision(event_logger, task_id=task_id, task_type="classify", decision=decision)

    assert event.task_id == task_id
