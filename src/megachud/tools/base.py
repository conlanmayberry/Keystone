from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from megachud.models.approval import RiskLevel

__all__ = ["RiskLevel", "Tool", "ToolResult", "ToolValidationError"]


class ToolValidationError(Exception):
    """Raised when a tool call's args fail validation before execution."""


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """Every tool the orchestrator can call. `risk_level` is what routes a
    call through the approval gate (see orchestrator.approval_gate) — Phase 1
    ships only LOW/MEDIUM tools, but a future HIGH_IRREVERSIBLE tool (web
    purchase, send email, post content) needs no orchestrator changes, only
    a new Tool subclass and a registry entry.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    risk_level: ClassVar[RiskLevel]

    @abstractmethod
    def validate_args(self, args: dict[str, Any]) -> None:
        """Raise ToolValidationError if args are malformed."""

    @abstractmethod
    def run(self, args: dict[str, Any]) -> ToolResult:
        ...
