from __future__ import annotations

from typing import Any, ClassVar

import httpx

from megachud.models.approval import RiskLevel
from megachud.tools.base import Tool, ToolResult, ToolValidationError


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web via the Brave Search API and return titles/URLs/snippets."
    risk_level = RiskLevel.LOW

    _ENDPOINT: ClassVar[str] = "https://api.search.brave.com/res/v1/web/search"

    def __init__(
        self,
        api_key: str,
        *,
        max_results: int = 10,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("query"), str) or not args["query"].strip():
            raise ToolValidationError("'query' (non-empty str) is required")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        query = args["query"]
        count = min(args.get("count", self.max_results) or self.max_results, self.max_results)

        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = client.get(
                    self._ENDPOINT,
                    headers={"X-Subscription-Token": self._api_key, "Accept": "application/json"},
                    params={"q": query, "count": count},
                )
        except httpx.TimeoutException:
            return ToolResult(success=False, output="", error=f"search timed out after {self.timeout_seconds}s")
        except httpx.TransportError as exc:
            return ToolResult(success=False, output="", error=f"search request failed: {exc}")

        if response.status_code != 200:
            return ToolResult(
                success=False, output="",
                error=f"search API returned {response.status_code}: {response.text[:200]}",
            )

        try:
            payload = response.json()
            raw_results = payload.get("web", {}).get("results", [])
        except ValueError:
            return ToolResult(success=False, output="", error="search API returned malformed JSON")

        results = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
            for r in raw_results[: self.max_results]
        ]

        output = "\n".join(f"- {r['title']} ({r['url']}): {r['description']}" for r in results) or "(no results)"
        return ToolResult(success=True, output=output, metadata={"results": results, "query": query})
