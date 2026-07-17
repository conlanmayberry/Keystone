from __future__ import annotations

import httpx
import pytest

from megachud.internet import url_safety
from megachud.tools.internet_tools import DownloadFileTool


def _stub_public_resolver(monkeypatch):
    def fake_resolve(hostname: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(url_safety, "_resolve_hostname", fake_resolve)


def make_tool(workspace_root, transport, **kwargs):
    return DownloadFileTool(workspace_root, transport=transport, **kwargs)


def test_successful_download_lands_in_downloads_folder(tmp_workspace, monkeypatch):
    _stub_public_resolver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"file contents")

    tool = make_tool(tmp_workspace, httpx.MockTransport(handler))
    result = tool.run({"url": "https://example.com/report.txt"})

    assert result.success
    assert result.metadata["bytes_written"] == len(b"file contents")
    saved = tmp_workspace / "downloads" / "report.txt"
    assert saved.exists()
    assert saved.read_bytes() == b"file contents"


def test_explicit_filename_is_sanitized(tmp_workspace, monkeypatch):
    _stub_public_resolver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data")

    tool = make_tool(tmp_workspace, httpx.MockTransport(handler))
    result = tool.run({"url": "https://example.com/x", "filename": "../../etc/passwd"})

    assert result.success
    # only the trailing path segment survives sanitization
    assert result.metadata["path"] == "downloads/passwd"
    assert (tmp_workspace / "downloads" / "passwd").exists()
    # crucially, nothing escaped the workspace
    assert not (tmp_workspace.parent / "etc").exists()


def test_filename_from_content_disposition(tmp_workspace, monkeypatch):
    _stub_public_resolver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data", headers={"content-disposition": 'attachment; filename="report.pdf"'})

    tool = make_tool(tmp_workspace, httpx.MockTransport(handler))
    result = tool.run({"url": "https://example.com/download?id=1"})

    assert result.success
    assert result.metadata["path"] == "downloads/report.pdf"


def test_blocked_extension_rejected_before_any_write(tmp_workspace, monkeypatch):
    _stub_public_resolver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"MZ\x90\x00fake-exe-bytes")

    tool = make_tool(tmp_workspace, httpx.MockTransport(handler), blocked_extensions=[".exe"])
    result = tool.run({"url": "https://example.com/tool.exe"})

    assert not result.success
    assert "not allowed" in result.error
    assert not (tmp_workspace / "downloads").exists() or list((tmp_workspace / "downloads").iterdir()) == []


def test_per_file_size_cap_enforced_during_streaming(tmp_workspace, monkeypatch):
    _stub_public_resolver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"y" * 1000)

    tool = make_tool(tmp_workspace, httpx.MockTransport(handler), max_file_bytes=10)
    result = tool.run({"url": "https://example.com/huge.bin"})

    assert not result.success
    assert "exceeds max_file_bytes" in result.error
    downloads = tmp_workspace / "downloads"
    assert not downloads.exists() or list(downloads.iterdir()) == []


def test_folder_quota_rejected_without_touching_existing_files(tmp_workspace, monkeypatch):
    _stub_public_resolver(monkeypatch)
    downloads = tmp_workspace / "downloads"
    downloads.mkdir()
    existing = downloads / "old.txt"
    existing.write_bytes(b"z" * 90)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"n" * 50)

    tool = make_tool(tmp_workspace, httpx.MockTransport(handler), max_file_bytes=1000, max_folder_bytes=100)
    result = tool.run({"url": "https://example.com/new.txt"})

    assert not result.success
    assert "quota exceeded" in result.error
    assert existing.exists()
    assert existing.read_bytes() == b"z" * 90
    assert not (downloads / "new.txt").exists()


def test_filename_collision_gets_suffixed_not_overwritten(tmp_workspace, monkeypatch):
    _stub_public_resolver(monkeypatch)
    downloads = tmp_workspace / "downloads"
    downloads.mkdir()
    (downloads / "report.txt").write_bytes(b"original")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"new content")

    tool = make_tool(tmp_workspace, httpx.MockTransport(handler))
    result = tool.run({"url": "https://example.com/report.txt"})

    assert result.success
    assert (downloads / "report.txt").read_bytes() == b"original"
    assert result.metadata["path"] != "downloads/report.txt"


def test_private_ip_target_rejected_without_any_download(tmp_workspace, monkeypatch):
    def fake_resolve(hostname: str) -> list[str]:
        return ["127.0.0.1"]

    monkeypatch.setattr(url_safety, "_resolve_hostname", fake_resolve)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"should not be reached")

    tool = make_tool(tmp_workspace, httpx.MockTransport(handler))
    result = tool.run({"url": "http://internal.example/secret"})

    assert not result.success
    assert "non-public address" in result.error
    assert not (tmp_workspace / "downloads").exists()
