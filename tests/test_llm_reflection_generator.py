from __future__ import annotations

import json

from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.llm.client import LLMRequestError, LLMResponse
from megachud.models.event import Event
from megachud.models.evaluation import Evaluation
from megachud.models.task import Task
from megachud.reflection.llm_generator import LLMReflectionGenerator
from megachud.routing.engine import ModelProfile
from tests.fixtures.fake_llm_client import FakeLLMClient

PROFILES = [ModelProfile("test-model", cost_per_1k_input_tokens=0.001, cost_per_1k_output_tokens=0.002, quality_tier=1, est_latency_ms=100)]


def make_task(session_factory) -> Task:
    session = session_factory()
    try:
        task = Task(title="t", prompt="p", retry_count=0, result_summary="ok")
        session.add(task)
        session.commit()
        session.refresh(task)
        session.expunge(task)
        return task
    finally:
        session.close()


def make_evaluation(success: bool = True) -> Evaluation:
    return Evaluation(
        task_id="t1", success=success,
        checks_json=json.dumps([{"name": "tool_calls_succeeded", "passed": success, "detail": "d"}]),
    )


def good_response() -> LLMResponse:
    return LLMResponse(
        text="", tokens_input=100, tokens_output=50, model="test-model", stop_reason="tool_use",
        raw_tool_calls=[{
            "name": "submit_reflection",
            "input": {
                "what_worked": ["a"], "what_failed": [], "wrong_assumptions": [],
                "should_change": [], "become_long_term_knowledge": False,
            },
        }],
    )


def test_happy_path_parses_tool_use_into_draft(session_factory):
    task = make_task(session_factory)
    client = FakeLLMClient(response=good_response())
    event_logger = EventLogger(session_factory, EventBus())
    generator = LLMReflectionGenerator(client, "test-model", PROFILES, 1000, event_logger)

    draft = generator.generate(task, make_evaluation(), [])

    assert draft.what_worked == ["a"]
    assert draft.become_long_term_knowledge is False
    assert len(client.calls) == 1
    assert client.calls[0]["tool"]["name"] == "submit_reflection"


def test_falls_back_to_deterministic_on_llm_error(session_factory):
    task = make_task(session_factory)
    client = FakeLLMClient(error=LLMRequestError("boom", retryable=True))
    event_logger = EventLogger(session_factory, EventBus())
    generator = LLMReflectionGenerator(client, "test-model", PROFILES, 1000, event_logger)

    draft = generator.generate(task, make_evaluation(success=False), [])

    # DeterministicReflectionGenerator's real behavior: a failing check
    # produces a what_failed entry — proves the fallback actually ran.
    assert draft.what_failed
    assert draft.become_long_term_knowledge is True


def test_falls_back_when_no_tool_calls_in_response(session_factory):
    task = make_task(session_factory)
    client = FakeLLMClient(response=LLMResponse(text="oops, no tool call", tokens_input=5, tokens_output=5, model="test-model", stop_reason="end_turn"))
    event_logger = EventLogger(session_factory, EventBus())
    generator = LLMReflectionGenerator(client, "test-model", PROFILES, 1000, event_logger)

    draft = generator.generate(task, make_evaluation(), [])

    assert draft.what_worked  # deterministic fallback still produces real output


def test_falls_back_on_malformed_tool_input(session_factory):
    task = make_task(session_factory)
    malformed = LLMResponse(
        text="", tokens_input=10, tokens_output=10, model="test-model", stop_reason="tool_use",
        raw_tool_calls=[{"name": "submit_reflection", "input": {"what_worked": ["a"]}}],  # missing required fields
    )
    client = FakeLLMClient(response=malformed)
    event_logger = EventLogger(session_factory, EventBus())
    generator = LLMReflectionGenerator(client, "test-model", PROFILES, 1000, event_logger)

    draft = generator.generate(task, make_evaluation(), [])

    assert draft is not None  # did not raise


def test_cost_event_logged_only_on_success(session_factory):
    task = make_task(session_factory)
    client = FakeLLMClient(response=good_response())
    event_logger = EventLogger(session_factory, EventBus())
    generator = LLMReflectionGenerator(client, "test-model", PROFILES, 1000, event_logger)

    generator.generate(task, make_evaluation(), [])

    session = session_factory()
    try:
        events = session.query(Event).filter_by(event_type="llm_call", task_id=task.id).all()
        assert len(events) == 1
        assert events[0].tool_name == "llm:reflection"
        assert events[0].tokens_input == 100
        assert events[0].tokens_output == 50
        assert events[0].cost_usd == 0.001 / 1000 * 100 + 0.002 / 1000 * 50
    finally:
        session.close()


def test_no_cost_event_logged_on_fallback(session_factory):
    task = make_task(session_factory)
    client = FakeLLMClient(error=LLMRequestError("boom", retryable=True))
    event_logger = EventLogger(session_factory, EventBus())
    generator = LLMReflectionGenerator(client, "test-model", PROFILES, 1000, event_logger)

    generator.generate(task, make_evaluation(), [])

    session = session_factory()
    try:
        events = session.query(Event).filter_by(event_type="llm_call").all()
        assert events == []
    finally:
        session.close()
