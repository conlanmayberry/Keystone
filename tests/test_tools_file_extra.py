from __future__ import annotations

import pytest

from megachud.tools.base import ToolValidationError
from megachud.tools.file_tools import AppendFileTool, ListDirectoryTool, SearchFilesTool


def test_append_creates_then_appends(tmp_workspace):
    tool = AppendFileTool(tmp_workspace)

    r1 = tool.run({"path": "notes.txt", "content": "line one\n"})
    assert r1.success
    r2 = tool.run({"path": "notes.txt", "content": "line two\n"})
    assert r2.success

    assert (tmp_workspace / "notes.txt").read_text() == "line one\nline two\n"
    assert r2.metadata["bytes_appended"] == len("line two\n")


def test_append_rejects_sandbox_escape(tmp_workspace):
    tool = AppendFileTool(tmp_workspace)
    result = tool.run({"path": "../escape.txt", "content": "nope"})
    assert not result.success
    assert "escapes workspace" in result.error
    assert not (tmp_workspace.parent / "escape.txt").exists()


def test_list_directory(tmp_workspace):
    (tmp_workspace / "a.txt").write_text("hello")
    (tmp_workspace / "sub").mkdir()
    tool = ListDirectoryTool(tmp_workspace)

    result = tool.run({})
    assert result.success
    assert "sub/" in result.output
    assert "a.txt (5 bytes)" in result.output
    assert result.metadata["count"] == 2


def test_list_directory_not_a_dir(tmp_workspace):
    (tmp_workspace / "a.txt").write_text("hi")
    tool = ListDirectoryTool(tmp_workspace)
    result = tool.run({"path": "a.txt"})
    assert not result.success
    assert "not a directory" in result.error


def test_list_directory_rejects_escape(tmp_workspace):
    tool = ListDirectoryTool(tmp_workspace)
    result = tool.run({"path": "../.."})
    assert not result.success
    assert "escapes workspace" in result.error


def test_search_files_finds_matches(tmp_workspace):
    (tmp_workspace / "a.txt").write_text("alpha\nbeta needle here\ngamma")
    (tmp_workspace / "sub").mkdir()
    (tmp_workspace / "sub" / "b.txt").write_text("no match\nanother NEEDLE line")
    tool = SearchFilesTool(tmp_workspace)

    result = tool.run({"query": "needle"})
    assert result.success
    assert "a.txt:2:" in result.output
    assert "sub/b.txt:2:" in result.output
    assert result.metadata["match_count"] == 2


def test_search_files_no_matches(tmp_workspace):
    (tmp_workspace / "a.txt").write_text("nothing here")
    tool = SearchFilesTool(tmp_workspace)
    result = tool.run({"query": "zzz"})
    assert result.success
    assert result.output == "(no matches)"


def test_search_files_requires_query(tmp_workspace):
    tool = SearchFilesTool(tmp_workspace)
    with pytest.raises(ToolValidationError):
        tool.run({})


def test_search_skips_binary_files(tmp_workspace):
    (tmp_workspace / "bin.dat").write_bytes(b"\x00\x01needle\x02\xff")
    (tmp_workspace / "text.txt").write_text("needle in text")
    tool = SearchFilesTool(tmp_workspace)
    result = tool.run({"query": "needle"})
    assert result.metadata["match_count"] == 1
    assert "text.txt" in result.output
