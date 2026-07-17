from __future__ import annotations

import anthropic
import httpx
import pytest

from megachud.llm.client import AnthropicLLMClient, LLMRequestError, LLMResponse
from tests.fixtures.fake_llm_client import FakeLLMClient


def test_fake_client_returns_configured_response():
    response = LLMResponse(text="hi", tokens_input=10, tokens_output=5, model="m", stop_reason="end_turn")
    client = FakeLLMClient(response=response)

    result = client.complete(model="m", system="s", messages=[{"role": "user", "content": "hello"}], max_tokens=100)

    assert result is response
    assert client.calls[0]["model"] == "m"
    assert client.calls[0]["messages"] == [{"role": "user", "content": "hello"}]


def test_fake_client_raises_configured_error():
    client = FakeLLMClient(error=LLMRequestError("boom", retryable=False))

    with pytest.raises(LLMRequestError):
        client.complete(model="m", system="s", messages=[], max_tokens=10)


# --- AnthropicLLMClient: request shape + response parsing + exception mapping ---


class _FakeContentBlock:
    def __init__(self, type_: str, **kwargs):
        self.type = type_
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeAnthropicResponse:
    def __init__(self, content, usage, model, stop_reason):
        self.content = content
        self.usage = usage
        self.model = model
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, response=None, exception=None):
        self._response = response
        self._exception = exception
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._exception is not None:
            raise self._exception
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response=None, exception=None):
        self.messages = _FakeMessages(response=response, exception=exception)


def _patch_anthropic(monkeypatch, fake_client_instance) -> None:
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: fake_client_instance)


def test_request_shape_without_tool(monkeypatch):
    response = _FakeAnthropicResponse(
        content=[_FakeContentBlock("text", text="hello world")],
        usage=_FakeUsage(input_tokens=12, output_tokens=7),
        model="claude-sonnet-5",
        stop_reason="end_turn",
    )
    fake = _FakeAnthropicClient(response=response)
    _patch_anthropic(monkeypatch, fake)

    client = AnthropicLLMClient(api_key="sk-test", timeout_seconds=30.0)
    result = client.complete(model="claude-sonnet-5", system="sys", messages=[{"role": "user", "content": "hi"}], max_tokens=50)

    assert result.text == "hello world"
    assert result.tokens_input == 12
    assert result.tokens_output == 7
    assert result.model == "claude-sonnet-5"
    assert result.stop_reason == "end_turn"
    assert fake.messages.last_kwargs["model"] == "claude-sonnet-5"
    assert fake.messages.last_kwargs["max_tokens"] == 50
    assert fake.messages.last_kwargs["system"] == "sys"
    assert "tools" not in fake.messages.last_kwargs
    assert "tool_choice" not in fake.messages.last_kwargs


def test_request_shape_with_tool_forces_tool_choice(monkeypatch):
    response = _FakeAnthropicResponse(
        content=[_FakeContentBlock("tool_use", name="submit", input={"a": 1})],
        usage=_FakeUsage(input_tokens=5, output_tokens=3),
        model="claude-haiku-4-5-20251001",
        stop_reason="tool_use",
    )
    fake = _FakeAnthropicClient(response=response)
    _patch_anthropic(monkeypatch, fake)

    client = AnthropicLLMClient(api_key="sk-test")
    tool_schema = {"name": "submit", "description": "d", "input_schema": {"type": "object"}}
    result = client.complete(model="m", system="s", messages=[], max_tokens=10, tool=tool_schema)

    assert result.raw_tool_calls == [{"name": "submit", "input": {"a": 1}}]
    assert fake.messages.last_kwargs["tools"] == [tool_schema]
    assert fake.messages.last_kwargs["tool_choice"] == {"type": "tool", "name": "submit"}


def test_connection_error_is_retryable(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    fake = _FakeAnthropicClient(exception=anthropic.APIConnectionError(request=request))
    _patch_anthropic(monkeypatch, fake)

    client = AnthropicLLMClient(api_key="sk-test")
    with pytest.raises(LLMRequestError) as exc_info:
        client.complete(model="m", system="s", messages=[], max_tokens=10)
    assert exc_info.value.retryable is True


def test_rate_limit_error_is_retryable_with_status_429(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request, json={"error": {"message": "rate limited"}})
    fake = _FakeAnthropicClient(
        exception=anthropic.RateLimitError("rate limited", response=response, body={"error": {"message": "rate limited"}})
    )
    _patch_anthropic(monkeypatch, fake)

    client = AnthropicLLMClient(api_key="sk-test")
    with pytest.raises(LLMRequestError) as exc_info:
        client.complete(model="m", system="s", messages=[], max_tokens=10)
    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 429


def test_server_error_status_is_retryable(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(500, request=request, json={"error": {"message": "server error"}})
    fake = _FakeAnthropicClient(
        exception=anthropic.APIStatusError("server error", response=response, body={"error": {"message": "server error"}})
    )
    _patch_anthropic(monkeypatch, fake)

    client = AnthropicLLMClient(api_key="sk-test")
    with pytest.raises(LLMRequestError) as exc_info:
        client.complete(model="m", system="s", messages=[], max_tokens=10)
    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 500


def test_client_error_status_is_not_retryable(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(400, request=request, json={"error": {"message": "bad request"}})
    fake = _FakeAnthropicClient(
        exception=anthropic.APIStatusError("bad request", response=response, body={"error": {"message": "bad request"}})
    )
    _patch_anthropic(monkeypatch, fake)

    client = AnthropicLLMClient(api_key="sk-test")
    with pytest.raises(LLMRequestError) as exc_info:
        client.complete(model="m", system="s", messages=[], max_tokens=10)
    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 400
