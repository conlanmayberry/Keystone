from __future__ import annotations

import json

import httpx

from megachud.tools.web_search_tool import WebSearchTool


def make_tool(transport, **kwargs):
    return WebSearchTool("test-api-key", transport=transport, **kwargs)


def test_successful_search_parses_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "test-api-key"
        assert request.url.params["q"] == "megachud"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"title": "MegaChud", "url": "https://example.com/megachud", "description": "an agent platform"},
                    ]
                }
            },
        )

    tool = make_tool(httpx.MockTransport(handler))
    result = tool.run({"query": "megachud"})

    assert result.success
    assert result.metadata["results"] == [
        {"title": "MegaChud", "url": "https://example.com/megachud", "description": "an agent platform"}
    ]
    assert "MegaChud" in result.output


def test_results_capped_at_max_results():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"web": {"results": [{"title": f"r{i}", "url": f"https://x/{i}", "description": ""} for i in range(20)]}},
        )

    tool = make_tool(httpx.MockTransport(handler), max_results=3)
    result = tool.run({"query": "anything"})

    assert result.success
    assert len(result.metadata["results"]) == 3


def test_no_results_returns_success_with_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"web": {"results": []}})

    tool = make_tool(httpx.MockTransport(handler))
    result = tool.run({"query": "nothing found"})

    assert result.success
    assert result.metadata["results"] == []
    assert "no results" in result.output


def test_non_200_status_returns_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    tool = make_tool(httpx.MockTransport(handler))
    result = tool.run({"query": "anything"})

    assert not result.success
    assert "401" in result.error


def test_malformed_json_returns_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json{{{")

    tool = make_tool(httpx.MockTransport(handler))
    result = tool.run({"query": "anything"})

    assert not result.success
    assert "malformed" in result.error


def test_timeout_is_reported_cleanly():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    tool = make_tool(httpx.MockTransport(handler))
    result = tool.run({"query": "anything"})

    assert not result.success
    assert "timed out" in result.error
