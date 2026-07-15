from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from megachud.tools.base import ToolResult


@dataclass
class ToolCall:
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionStep:
    step_number: int
    tool_call: ToolCall
    result: ToolResult | None = None
