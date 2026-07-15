from __future__ import annotations

from megachud.tools.file_tools import ReadFileTool, WriteFileTool


def test_write_then_read_roundtrip(tmp_workspace):
    writer = WriteFileTool(tmp_workspace)
    reader = ReadFileTool(tmp_workspace)

    write_result = writer.run({"path": "hello.txt", "content": "hi there"})
    assert write_result.success
    assert write_result.metadata["bytes_written"] == len(b"hi there")

    read_result = reader.run({"path": "hello.txt"})
    assert read_result.success
    assert read_result.output == "hi there"


def test_write_creates_parent_dirs(tmp_workspace):
    writer = WriteFileTool(tmp_workspace)
    result = writer.run({"path": "nested/dir/file.txt", "content": "x"})
    assert result.success
    assert (tmp_workspace / "nested" / "dir" / "file.txt").read_text() == "x"


def test_write_outside_workspace_is_rejected(tmp_workspace):
    writer = WriteFileTool(tmp_workspace)
    result = writer.run({"path": "../escape.txt", "content": "bad"})
    assert not result.success
    assert "escapes workspace" in result.error
    assert not (tmp_workspace.parent / "escape.txt").exists()


def test_read_missing_file_fails_cleanly(tmp_workspace):
    reader = ReadFileTool(tmp_workspace)
    result = reader.run({"path": "nope.txt"})
    assert not result.success
    assert "not found" in result.error


def test_read_missing_path_arg_raises_validation_error(tmp_workspace):
    from megachud.tools.base import ToolValidationError
    import pytest

    reader = ReadFileTool(tmp_workspace)
    with pytest.raises(ToolValidationError):
        reader.run({})
