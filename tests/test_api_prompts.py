from __future__ import annotations

import json

from fastapi.testclient import TestClient

from megachud.api.app import create_app
from megachud.conversation.prompt_drafter import PromptDrafter
from megachud.llm.client import LLMRequestError, LLMResponse
from megachud.models.event import Event
from megachud.routing.engine import ModelProfile
from tests.fixtures.fake_llm_client import FakeLLMClient


def configure_drafter(app, response=None, error=None) -> FakeLLMClient:
    fake_client = FakeLLMClient(response=response, error=error)
    app.state.prompt_drafter = PromptDrafter(fake_client, "test-model", 500)
    app.state.model_profiles = [
        ModelProfile("test-model", cost_per_1k_input_tokens=0.001, cost_per_1k_output_tokens=0.002, quality_tier=1, est_latency_ms=100)
    ]
    return fake_client


def test_draft_prompt_not_configured_returns_503(test_settings):
    app = create_app(test_settings)
    assert app.state.prompt_drafter is None
    with TestClient(app) as client:
        response = client.post("/prompts/draft", json={"raw_text": "write a haiku thing"})
        assert response.status_code == 503


def test_draft_prompt_happy_path(test_settings):
    app = create_app(test_settings)
    fake_response = LLMResponse(
        text="  Write a haiku about autonomous agents to a file named haiku.txt.  ",
        tokens_input=15, tokens_output=25, model="test-model", stop_reason="end_turn", raw_tool_calls=[],
    )
    fake_client = configure_drafter(app, response=fake_response)

    with TestClient(app) as client:
        response = client.post("/prompts/draft", json={"raw_text": "write a haiku thing"})

        assert response.status_code == 200
        body = response.json()
        assert body["prompt"] == "Write a haiku about autonomous agents to a file named haiku.txt."
        assert body["model"] == "test-model"

        # Sent as a plain-text call — no forced tool-use for a single string output.
        assert fake_client.calls[0]["tool"] is None
        assert fake_client.calls[0]["messages"] == [{"role": "user", "content": "write a haiku thing"}]

        session = app.state.session_factory()
        try:
            events = session.query(Event).filter_by(event_type="llm_call", tool_name="llm:prompt_drafter").all()
            assert len(events) == 1
            assert events[0].tokens_input == 15
            assert events[0].tokens_output == 25
            assert events[0].cost_usd is not None
            assert json.loads(events[0].payload_json)["consumer"] == "prompt_drafter"
        finally:
            session.close()


def test_draft_prompt_llm_request_error_returns_502(test_settings):
    app = create_app(test_settings)
    configure_drafter(app, error=LLMRequestError("boom", retryable=False))
    with TestClient(app) as client:
        response = client.post("/prompts/draft", json={"raw_text": "write a haiku thing"})
        assert response.status_code == 502
