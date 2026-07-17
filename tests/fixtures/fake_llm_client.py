"""Test fixture: a scriptable LLMClient double. No consumer test ever
constructs a real AnthropicLLMClient or hits the network — every LLM-
backed component's tests use this instead, mirroring
tests/fixtures/dummy_tools.py's role for Tool-based tests.
"""

from __future__ import annotations

from typing import Any

from megachud.llm.client import LLMClient, LLMError, LLMResponse


class FakeLLMClient(LLMClient):
    def __init__(
        self,
        response: LLMResponse | None = None,
        error: LLMError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        tool: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {"model": model, "system": system, "messages": messages, "max_tokens": max_tokens, "tool": tool}
        )
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        raise AssertionError("FakeLLMClient.complete() called with neither response nor error configured")
