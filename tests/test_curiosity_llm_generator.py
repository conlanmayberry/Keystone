from __future__ import annotations

from megachud.curiosity.llm_generator import LLMCuriosityTextGenerator
from megachud.llm.client import LLMRequestError, LLMResponse
from tests.fixtures.fake_llm_client import FakeLLMClient


def good_response() -> LLMResponse:
    return LLMResponse(
        text="", tokens_input=30, tokens_output=15, model="test-model", stop_reason="tool_use",
        raw_tool_calls=[{
            "name": "submit_curiosity_text",
            "input": {
                "question": "What is the right approach here?",
                "search_memory_description": "search for related deployment issues",
                "inspect_previous_work_description": "check prior deployment tasks",
            },
        }],
    )


def test_happy_path_parses_tool_use_into_curiosity_text():
    client = FakeLLMClient(response=good_response())
    generator = LLMCuriosityTextGenerator(client, "test-model", 500)

    result = generator.generate("deploy service", "deploy the web service", 0.1, 0.35)

    assert result.question == "What is the right approach here?"
    assert result.objective_descriptions["search_memory"] == "search for related deployment issues"
    assert result.objective_descriptions["inspect_previous_work"] == "check prior deployment tasks"
    assert result.tokens_input == 30
    assert result.tokens_output == 15
    assert result.model == "test-model"


def test_falls_back_to_deterministic_on_llm_error():
    client = FakeLLMClient(error=LLMRequestError("boom", retryable=True))
    generator = LLMCuriosityTextGenerator(client, "test-model", 500)

    result = generator.generate("deploy service", "deploy the web service", 0.1, 0.35)

    assert "deploy service" in result.question
    assert result.tokens_input == 0
    assert result.tokens_output == 0
    assert result.model is None


def test_falls_back_when_no_tool_calls_in_response():
    client = FakeLLMClient(response=LLMResponse(text="I refuse", tokens_input=5, tokens_output=5, model="test-model", stop_reason="end_turn"))
    generator = LLMCuriosityTextGenerator(client, "test-model", 500)

    result = generator.generate("t", "p", 0.1, 0.35)

    assert result.tokens_input == 0  # deterministic fallback, no fabricated cost


def test_falls_back_on_malformed_tool_input():
    malformed = LLMResponse(
        text="", tokens_input=10, tokens_output=10, model="test-model", stop_reason="tool_use",
        raw_tool_calls=[{"name": "submit_curiosity_text", "input": {"question": "only this field"}}],
    )
    client = FakeLLMClient(response=malformed)
    generator = LLMCuriosityTextGenerator(client, "test-model", 500)

    result = generator.generate("t", "p", 0.1, 0.35)

    assert result.tokens_input == 0
