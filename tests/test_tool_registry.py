from __future__ import annotations

import pytest

from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry


def test_register_and_get(tmp_workspace):
    registry = ToolRegistry()
    reader = ReadFileTool(tmp_workspace)
    registry.register(reader)

    assert registry.get("read_file") is reader


def test_duplicate_registration_raises(tmp_workspace):
    registry = ToolRegistry()
    registry.register(ReadFileTool(tmp_workspace))

    with pytest.raises(ValueError):
        registry.register(ReadFileTool(tmp_workspace))


def test_get_unknown_tool_raises(tmp_workspace):
    registry = ToolRegistry()
    with pytest.raises(KeyError):
        registry.get("does_not_exist")


def test_all_returns_registered_tools(tmp_workspace):
    registry = ToolRegistry()
    reader = ReadFileTool(tmp_workspace)
    writer = WriteFileTool(tmp_workspace)
    registry.register(reader)
    registry.register(writer)

    assert set(registry.all()) == {reader, writer}
