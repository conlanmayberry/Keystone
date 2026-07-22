from __future__ import annotations

import pytest

from megachud.conversation.prompt_drafter import PromptDrafter
from megachud.llm.client import LLMRequestError, LLMResponse
from tests.fixtures.fake_llm_client import FakeLLMClient


def test_draft_strips_whitespace_and_uses_plain_text_call():
    fake_client = FakeLLMClient(
        response=LLMResponse(
            text="  Write a haiku to haiku.txt.  ", tokens_input=10, tokens_output=8,
            model="test-model", stop_reason="end_turn", raw_tool_calls=[],
        )
    )
    drafter = PromptDrafter(fake_client, "test-model", 500)

    result = drafter.draft("write a haiku thing")

    assert result.prompt == "Write a haiku to haiku.txt."
    assert result.tokens_input == 10
    assert result.tokens_output == 8
    assert result.model == "test-model"

    call = fake_client.calls[0]
    assert call["tool"] is None
    assert call["messages"] == [{"role": "user", "content": "write a haiku thing"}]
    assert call["model"] == "test-model"
    assert call["max_tokens"] == 500


def test_llm_request_error_propagates_uncaught():
    fake_client = FakeLLMClient(error=LLMRequestError("boom", retryable=False))
    drafter = PromptDrafter(fake_client, "test-model", 500)

    with pytest.raises(LLMRequestError):
        drafter.draft("anything")
