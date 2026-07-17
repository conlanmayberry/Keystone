"""Convenience re-exports for plugin authors — `from megachud.plugins
import Tool` reads better in third-party code than reaching into
`megachud.tools.base`. No new types are defined here; these are exactly
the three existing ABC swap-points plugins can register implementations
of.
"""

from __future__ import annotations

from megachud.reflection.generator import ReflectionDraft, ReflectionGenerator
from megachud.routing.engine import ModelProfile, ModelRouter, RoutingDecision
from megachud.tools.base import RiskLevel, Tool, ToolResult, ToolValidationError

__all__ = [
    "ModelProfile",
    "ModelRouter",
    "ReflectionDraft",
    "ReflectionGenerator",
    "RiskLevel",
    "RoutingDecision",
    "Tool",
    "ToolResult",
    "ToolValidationError",
]
