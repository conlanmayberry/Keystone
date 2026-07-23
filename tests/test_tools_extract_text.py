from __future__ import annotations

import httpx
import pytest

from megachud.internet import url_safety
from megachud.tools.base import ToolValidationError
from megachud.tools.internet_tools import ExtractTextTool, html_to_text

SAMPLE_HTML = """
<html><head><title>T</title><style>.x{color:red}</style></head>
<body>
  <h1>Heading</h1>
  <p>First paragraph with <a href="/x">a link</a>.</p>
  <script>console.log('should be dropped')</script>
  <p>Second paragraph.</p>
</body></html>
"""


def _stub_public_resolver(monkeypatch):
    monkeypatch.setattr(url_safety, "_resolve_hostname", lambda h: ["93.184.216.34"])


def test_html_to_text_drops_script_and_style():
    text = html_to_text(SAMPLE_HTML)
    assert "Heading" in text
    assert "First paragraph with a link." in text
    assert "Second paragraph." in text
    assert "console.log" not in text
    assert "color:red" not in text


def test_extract_text_from_html_arg():
    tool = ExtractTextTool()
    result = tool.run({"html": "<p>Hello <b>world</b></p><script>x()</script>"})
    assert result.success
    assert result.output.strip() == "Hello world"
    assert result.metadata["source"] == "html"


def test_extract_text_from_url(monkeypatch):
    _stub_public_resolver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_HTML)

    tool = ExtractTextTool(transport=httpx.MockTransport(handler))
    result = tool.run({"url": "https://example.com/page"})

    assert result.success
    assert "Heading" in result.output
    assert "console.log" not in result.output
    assert result.metadata["source"] == "url"


def test_extract_text_url_ssrf_rejected(monkeypatch):
    monkeypatch.setattr(url_safety, "_resolve_hostname", lambda h: ["127.0.0.1"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="should not be reached")

    tool = ExtractTextTool(transport=httpx.MockTransport(handler))
    result = tool.run({"url": "http://internal.example/"})
    assert not result.success
    assert "non-public address" in result.error


def test_extract_text_requires_url_or_html():
    tool = ExtractTextTool()
    with pytest.raises(ToolValidationError):
        tool.run({})
