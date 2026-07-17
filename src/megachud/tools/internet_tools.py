from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit

import httpx

from megachud.internet.url_safety import UrlSafetyError, check_url_safety
from megachud.models.approval import RiskLevel
from megachud.tools.base import Tool, ToolResult, ToolValidationError
from megachud.workspace.sandbox import WorkspaceEscapeError, resolve_safe_path


class TooManyRedirectsError(Exception):
    pass


@contextmanager
def open_validated_stream(
    url: str,
    *,
    timeout_seconds: float,
    max_redirects: int,
    domain_allowlist: list[str] | None,
    domain_denylist: list[str] | None,
    transport: httpx.BaseTransport | None,
) -> Iterator[tuple[httpx.Response, int]]:
    """Open a streamed GET, following redirects manually so every hop
    (including the first) can be re-validated through check_url_safety()
    before connecting. httpx's own follow_redirects=True does NOT
    re-validate hops, which would let a server 302 the request to a
    private/internal address after the original URL passed its safety
    check — a well-known SSRF bypass this deliberately avoids.

    Yields (response, redirect_count) for the final, non-redirect
    response, still open for streaming. The underlying client and
    response are closed when the `with` block exits.
    """
    current_url = url
    with httpx.Client(timeout=timeout_seconds, follow_redirects=False, transport=transport) as client:
        redirect_count = 0
        while True:
            check_url_safety(current_url, domain_allowlist=domain_allowlist, domain_denylist=domain_denylist)
            request = client.build_request("GET", current_url)
            response = client.send(request, stream=True)

            if response.is_redirect:
                response.close()
                redirect_count += 1
                if redirect_count > max_redirects:
                    raise TooManyRedirectsError(f"exceeded max_redirects={max_redirects}")
                location = response.headers.get("location")
                if not location:
                    raise TooManyRedirectsError("redirect response had no Location header")
                current_url = urljoin(current_url, location)
                continue

            try:
                yield response, redirect_count
            finally:
                response.close()
            return


def _read_capped(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    """Read response.iter_bytes(), aborting the moment accumulated bytes
    exceed max_bytes — never trusts Content-Length alone, since a
    malicious or misconfigured server can lie about it."""
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
            with open_validated_stream(
                url,
                timeout_seconds=self.timeout_seconds,
                max_redirects=self.max_redirects,
                domain_allowlist=self.domain_allowlist,
                domain_denylist=self.domain_denylist,
                transport=self._transport,
            ) as (response, redirect_count):
                body, truncated = _read_capped(response, self.max_response_bytes)
                status_code = response.status_code
                final_url = str(response.url)
                encoding = response.encoding
        except (UrlSafetyError, TooManyRedirectsError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        except httpx.TimeoutException:
            return ToolResult(success=False, output="", error=f"request timed out after {self.timeout_seconds}s")
        except httpx.TransportError as exc:
            return ToolResult(success=False, output="", error=f"request failed: {exc}")

        text = body.decode(encoding or "utf-8", errors="replace")
        return ToolResult(
            success=True,
            output=text,
            metadata={
                "status_code": status_code,
                "final_url": final_url,
                "bytes_read": len(body),
                "truncated": truncated,
                "redirect_count": redirect_count,
            },
        )


def _sanitize_filename(raw: str) -> str:
    """Strip path separators, traversal sequences, and non-safe characters
    from a server-suggested or user-suggested filename BEFORE it is ever
    passed to resolve_safe_path — sandbox.py only confines paths, it has
    no filename sanitizer of its own."""
    name = raw.strip().replace("\\", "/").split("/")[-1]
    name = name.replace("..", "")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".")
    return name[:200] or f"download_{uuid.uuid4().hex[:8]}"


def _filename_from_content_disposition(header_value: str | None) -> str | None:
    if not header_value:
        return None
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header_value)
    return match.group(1) if match else None


def _folder_usage_bytes(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(f.stat().st_size for f in folder.iterdir() if f.is_file())


class DownloadFileTool(Tool):
    name = "download_file"
    description = (
        "Download a URL's content into workspace/downloads/. Enforces the "
        "same SSRF/scheme checks as http_fetch, a per-file size cap, a "
        "total-folder disk quota, a blocked-extension list for obviously "
        "executable file types, and filename sanitization against path "
        "traversal."
    )
    risk_level = RiskLevel.MEDIUM

    def __init__(
        self,
        workspace_root: Path,
        *,
        max_file_bytes: int = 25_000_000,
        max_folder_bytes: int = 500_000_000,
        blocked_extensions: list[str] | None = None,
        timeout_seconds: float = 30.0,
        max_redirects: int = 5,
        domain_allowlist: list[str] | None = None,
        domain_denylist: list[str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.max_file_bytes = max_file_bytes
        self.max_folder_bytes = max_folder_bytes
        self.blocked_extensions = {e.lower() for e in (blocked_extensions or [])}
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.domain_allowlist = domain_allowlist
        self.domain_denylist = domain_denylist
        self._transport = transport

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("url"), str) or not args["url"].strip():
            raise ToolValidationError("'url' (non-empty str) is required")
        if "filename" in args and not isinstance(args["filename"], str):
            raise ToolValidationError("'filename' must be a str if provided")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        url = args["url"]

        try:
            with open_validated_stream(
                url,
                timeout_seconds=self.timeout_seconds,
                max_redirects=self.max_redirects,
                domain_allowlist=self.domain_allowlist,
                domain_denylist=self.domain_denylist,
                transport=self._transport,
            ) as (response, _redirect_count):
                return self._save_response(response, args, url)
        except (UrlSafetyError, TooManyRedirectsError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        except httpx.TimeoutException:
            return ToolResult(success=False, output="", error=f"request timed out after {self.timeout_seconds}s")
        except httpx.TransportError as exc:
            return ToolResult(success=False, output="", error=f"request failed: {exc}")

    def _save_response(self, response: httpx.Response, args: dict[str, Any], url: str) -> ToolResult:
        raw_name = (
            args.get("filename")
            or _filename_from_content_disposition(response.headers.get("content-disposition"))
            or urlsplit(url).path.rsplit("/", 1)[-1]
        )
        filename = _sanitize_filename(raw_name)

        suffix = Path(filename).suffix.lower()
        if suffix in self.blocked_extensions:
            return ToolResult(success=False, output="", error=f"file extension not allowed: {suffix!r}")

        downloads_dir = self.workspace_root / "downloads"
        try:
            final_path = resolve_safe_path(downloads_dir, filename)
        except WorkspaceEscapeError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        downloads_dir.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            final_path = final_path.with_name(f"{final_path.stem}_{uuid.uuid4().hex[:8]}{final_path.suffix}")

        part_path = final_path.with_suffix(final_path.suffix + ".part")
        bytes_written = 0
        try:
            with part_path.open("wb") as f:
                for chunk in response.iter_bytes():
                    bytes_written += len(chunk)
                    if bytes_written > self.max_file_bytes:
                        f.close()
                        part_path.unlink(missing_ok=True)
                        return ToolResult(
                            success=False, output="",
                            error=f"file exceeds max_file_bytes={self.max_file_bytes}, download aborted",
                        )
                    f.write(chunk)
        except httpx.TransportError as exc:
            part_path.unlink(missing_ok=True)
            return ToolResult(success=False, output="", error=f"download failed mid-stream: {exc}")

        # Total usage INCLUDING the just-written .part file — comparing
        # this against the quota after the write is equivalent to
        # "pre-existing total + new file size > quota", just computed via
        # one directory scan instead of two.
        total_usage_with_new_file = _folder_usage_bytes(downloads_dir)
        if total_usage_with_new_file > self.max_folder_bytes:
            part_path.unlink(missing_ok=True)
            return ToolResult(
                success=False, output="",
                error=(
                    f"downloads folder quota exceeded "
                    f"({total_usage_with_new_file} > {self.max_folder_bytes} bytes); "
                    "download rejected, no existing files were touched"
                ),
            )

        part_path.rename(final_path)
        relative_path = f"downloads/{final_path.name}"
        return ToolResult(
            success=True,
            output=f"downloaded {bytes_written} bytes to {relative_path}",
            metadata={
                "path": relative_path,
                "bytes_written": bytes_written,
                "folder_usage_bytes": total_usage_with_new_file,
                "folder_quota_bytes": self.max_folder_bytes,
                "status_code": response.status_code,
            },
        )
