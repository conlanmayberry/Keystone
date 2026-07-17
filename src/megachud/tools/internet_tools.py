from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from megachud.internet.url_safety import UrlSafetyError, check_url_safety
from megachud.models.approval import RiskLevel
from megachud.tools.base import Tool, ToolResult, ToolValidationError


class TooManyRedirectsError(Exception):
    pass


@dataclass
class FetchedResponse:
    body: bytes
    truncated: bool
    status_code: int
    final_url: str
    redirect_count: int
    headers: httpx.Headers
    encoding: str | None


def fetch_with_validated_redirects(
    url: str,
    *,
    max_response_bytes: int,
    timeout_seconds: float,
    max_redirects: int,
    domain_allowlist: list[str] | None,
    domain_denylist: list[str] | None,
    transport: httpx.BaseTransport | None,
) -> FetchedResponse:
    """Streamed GET with a manual, bounded redirect loop — httpx's own
    follow_redirects=True does NOT re-validate each hop, which would let a
    server 302 the request to a private/internal address after the
    original URL passed its safety check (a well-known SSRF bypass).
    Every hop, including the first, goes through check_url_safety().

    The body is read in a capped stream — never trusts Content-Length
    alone, since a malicious or misconfigured server can lie about it.
    The whole fetch happens inside one `with httpx.Client(...)` so the
    connection is always closed, regardless of outcome.
    """
    current_url = url
    with httpx.Client(timeout=timeout_seconds, follow_redirects=False, transport=transport) as client:
        redirect_count = 0
        while True:
            check_url_safety(current_url, domain_allowlist=domain_allowlist, domain_denylist=domain_denylist)
            request = client.build_request("GET", current_url)
            response = client.send(request, stream=True)
            try:
                if response.is_redirect:
                    redirect_count += 1
                    if redirect_count > max_redirects:
                        raise TooManyRedirectsError(f"exceeded max_redirects={max_redirects}")
                    location = response.headers.get("location")
                    if not location:
                        raise TooManyRedirectsError("redirect response had no Location header")
                    current_url = urljoin(current_url, location)
                    continue

                body, truncated = _read_capped(response, max_response_bytes)
                return FetchedResponse(
                    body=body,
                    truncated=truncated,
                    status_code=response.status_code,
                    final_url=str(response.url),
                    redirect_count=redirect_count,
                    headers=response.headers,
                    encoding=response.encoding,
                )
            finally:
                response.close()


def _read_capped(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    """Read response.iter_bytes(), aborting the moment accumulated bytes
    exceed max_bytes."""
    chunks: list[bytes] = []
    total = 0
    truncated = False
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            remaining = max_bytes - (total - len(chunk))
            if remaining > 0:
                chunks.append(chunk[:remaining])
            truncated = True
            break
        chunks.append(chunk)
    return b"".join(chunks), truncated


class HttpFetchTool(Tool):
    name = "http_fetch"
    description = (
        "Fetch a URL via HTTP(S) GET and return its text content. Enforces "
        "scheme allowlisting and an SSRF guard (rejects private/loopback/"
        "link-local network targets) on the URL and every redirect hop — "
        "this is network-safety hygiene, not a phishing/malicious-content "
        "detector."
    )
    risk_level = RiskLevel.LOW

    def __init__(
        self,
        *,
        max_response_bytes: int = 2_000_000,
        timeout_seconds: float = 15.0,
        max_redirects: int = 5,
        domain_allowlist: list[str] | None = None,
        domain_denylist: list[str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.max_response_bytes = max_response_bytes
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.domain_allowlist = domain_allowlist
        self.domain_denylist = domain_denylist
        self._transport = transport

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("url"), str) or not args["url"].strip():
            raise ToolValidationError("'url' (non-empty str) is required")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        url = args["url"]

        try:
            fetched = fetch_with_validated_redirects(
                url,
                max_response_bytes=self.max_response_bytes,
                timeout_seconds=self.timeout_seconds,
                max_redirects=self.max_redirects,
                domain_allowlist=self.domain_allowlist,
                domain_denylist=self.domain_denylist,
                transport=self._transport,
            )
        except (UrlSafetyError, TooManyRedirectsError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        except httpx.TimeoutException:
            return ToolResult(success=False, output="", error=f"request timed out after {self.timeout_seconds}s")
        except httpx.TransportError as exc:
            return ToolResult(success=False, output="", error=f"request failed: {exc}")

        text = fetched.body.decode(fetched.encoding or "utf-8", errors="replace")
        return ToolResult(
            success=True,
            output=text,
            metadata={
                "status_code": fetched.status_code,
                "final_url": fetched.final_url,
                "bytes_read": len(fetched.body),
                "truncated": fetched.truncated,
                "redirect_count": fetched.redirect_count,
            },
        )
