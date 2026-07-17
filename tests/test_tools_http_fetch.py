from __future__ import annotations

import httpx
import pytest

from megachud.internet import url_safety
from megachud.tools.base import ToolValidationError
from megachud.tools.internet_tools import HttpFetchTool


def _stub_public_resolver(monkeypatch, hostnames: list[str] | None = None):
    def fake_resolve(hostname: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(url_safety, "_resolve_hostname", fake_resolve)


def make_tool(transport, **kwargs):
    return HttpFetchTool(transport=transport, **kwargs)


def test_successful_fetch_returns_text(monkeypatch):
    _stub_public_resolver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"hello world")

    tool = make_tool(httpx.MockTransport(handler))
    result = tool.run({"url": "https://example.com/page"})

    assert result.success
    assert result.output == "hello world"
    assert result.metadata["status_code"] == 200
    assert result.metadata["truncated"] is False
    assert result.metadata["redirect_count"] == 0


def test_response_larger_than_cap_is_truncated(monkeypatch):
    _stub_public_resolver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1000)

    tool = make_tool(httpx.MockTransport(handler), max_response_bytes=10)
    result = tool.run({"url": "https://example.com/big"})

    assert result.success
    assert len(result.output) == 10
    assert result.metadata["truncated"] is True


def test_redirect_is_followed_and_revalidated(monkeypatch):
    _stub_public_resolver(monkeypatch)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == "https://example.com/start":
            return httpx.Response(302, headers={"location": "https://example.com/final"})
        return httpx.Response(200, content=b"final page")

    tool = make_tool(httpx.MockTransport(handler))
    result = tool.run({"url": "https://example.com/start"})

    assert result.success
    assert result.output == "final page"
    assert result.metadata["redirect_count"] == 1
    assert len(calls) == 2


def test_redirect_to_unsafe_address_is_rejected(monkeypatch):
    def fake_resolve(hostname: str) -> list[str]:
        if hostname == "internal.example":
            return ["127.0.0.1"]
        return ["93.184.216.34"]

    monkeypatch.setattr(url_safety, "_resolve_hostname", fake_resolve)

    def handler(request: httpx.Request) -> httpx.Response:
        if "start" in str(request.url):
            return httpx.Response(302, headers={"location": "https://internal.example/secret"})
        return httpx.Response(200, content=b"should never get here")

    tool = make_tool(httpx.MockTransport(handler))
    result = tool.run({"url": "https://example.com/start"})

    assert not result.success
    assert "non-public address" in result.error


def test_too_many_redirects_is_rejected(monkeypatch):
    _stub_public_resolver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/next"})

    tool = make_tool(httpx.MockTransport(handler), max_redirects=2)
    result = tool.run({"url": "https://example.com/start"})

    assert not result.success
    assert "max_redirects" in result.error


def test_timeout_is_reported_cleanly(monkeypatch):
    _stub_public_resolver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    tool = make_tool(httpx.MockTransport(handler))
    result = tool.run({"url": "https://example.com/slow"})

    assert not result.success
    assert "timed out" in result.error


def test_private_ip_target_rejected_without_any_request(monkeypatch):
    def fake_resolve(hostname: str) -> list[str]:
        return ["10.0.0.5"]

    monkeypatch.setattr(url_safety, "_resolve_hostname", fake_resolve)
    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, content=b"should not be reached")

    tool = make_tool(httpx.MockTransport(handler))
    result = tool.run({"url": "http://internal.example/"})

    assert not result.success
    assert "non-public address" in result.error
    assert called == []


def test_missing_url_arg_rejected():
    tool = make_tool(httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ToolValidationError, match="url"):
        tool.run({})
