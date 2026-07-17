from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    text: str
    tokens_input: int
    tokens_output: int
    model: str
    stop_reason: str
    raw_tool_calls: list[dict[str, Any]] = field(default_factory=list)


class LLMError(Exception):
    """Base class for all LLM call failures raised by this module."""


class LLMNotConfiguredError(LLMError):
    """No API key configured — raised before any network call is attempted."""


class LLMRequestError(LLMError):
    """Wraps a request-level failure: auth, bad request, rate limit,
    timeout, connection, server error. `retryable` lets a caller decide
    whether to bubble up or degrade gracefully — none of this project's
    consumers currently retry, they each fall back to a deterministic
    implementation on any failure instead.
    """

    def __init__(self, message: str, *, retryable: bool, status_code: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class LLMClient(ABC):
    """4th swap-point in this codebase, mirroring Tool/ReflectionGenerator/
    ModelRouter. Every unit test uses a FakeLLMClient double — no real
    network calls anywhere in the test suite. AnthropicLLMClient is the
    only real implementation, constructed only when create_app() has a
    configured API key.
    """

    @abstractmethod
    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        tool: dict[str, Any] | None = None,
    ) -> LLMResponse: ...


class AnthropicLLMClient(LLMClient):
    """Thin wrapper over anthropic.Anthropic(). Structured output uses
    forced tool-use (tool_choice), not "respond in JSON" + json.loads:
    a plain JSON-prompt has no schema enforcement — Claude can preface
    with prose, wrap in markdown fences, or emit invalid JSON, with only
    a bare parse-and-hope fallback. Forcing a single tool call validates
    the response's `input` against the tool's input_schema server-side
    before it's ever returned — no prose to strip, no markdown fence to
    regex out. Matches this codebase's existing validate-everything
    convention (Tool.validate_args, pydantic everywhere).
    """

    def __init__(self, api_key: str, timeout_seconds: float = 60.0) -> None:
        # Local import: keeps `llm/` importable (and this module's ABC
        # usable for FakeLLMClient-based tests) even without the anthropic
        # package installed, and keeps it off the hot import path for
        # anyone who never configures a key.
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        tool: dict[str, Any] | None = None,
    ) -> LLMResponse:
        import anthropic

        kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
        if tool is not None:
            kwargs["tools"] = [tool]
            kwargs["tool_choice"] = {"type": "tool", "name": tool["name"]}

        try:
            response = self._client.messages.create(**kwargs)
        except anthropic.APIConnectionError as exc:
            raise LLMRequestError(f"connection error calling Anthropic API: {exc}", retryable=True) from exc
        except anthropic.RateLimitError as exc:
            raise LLMRequestError(f"rate limited: {exc}", retryable=True, status_code=429) from exc
        except anthropic.APIStatusError as exc:
            raise LLMRequestError(
                f"Anthropic API error ({exc.status_code}): {exc.message}",
                retryable=exc.status_code >= 500,
                status_code=exc.status_code,
            ) from exc

        text_parts = [block.text for block in response.content if block.type == "text"]
        tool_calls = [
            {"name": block.name, "input": block.input} for block in response.content if block.type == "tool_use"
        ]
        return LLMResponse(
            text="".join(text_parts),
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
            model=response.model,
            stop_reason=response.stop_reason,
            raw_tool_calls=tool_calls,
        )
