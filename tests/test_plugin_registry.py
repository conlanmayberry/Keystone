from __future__ import annotations

from typing import Any

import pytest

from megachud.plugins.registry import PluginRegistry
from megachud.reflection.generator import DeterministicReflectionGenerator, ReflectionDraft, ReflectionGenerator
from megachud.routing.engine import ModelRouter, RoutingDecision
from megachud.tools.base import RiskLevel, Tool, ToolResult
from megachud.tools.registry import ToolRegistry


class _OkTool(Tool):
    name = "ok_tool"
    description = "d"
    risk_level = RiskLevel.LOW

    def validate_args(self, args: dict[str, Any]) -> None:
        pass

    def run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="ok")


class _NoRiskLevelTool(Tool):
    name = "no_risk_level"
    description = "d"

    def validate_args(self, args: dict[str, Any]) -> None:
        pass

    def run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="ok")


class _StubModelRouter(ModelRouter):
    def route(self, task_type, quality_target, est_tokens_input=0, est_tokens_output=0) -> RoutingDecision:
        return RoutingDecision(chosen_model="stub", reason="r", estimated_cost_usd=0.0, candidates_considered=["stub"])


def test_register_tool_delegates_to_real_registry():
    tool_registry = ToolRegistry()
    plugin_registry = PluginRegistry(tool_registry)

    plugin_registry.register_tool(_OkTool())

    assert tool_registry.get("ok_tool") is not None


def test_register_tool_rejects_missing_risk_level():
    plugin_registry = PluginRegistry(ToolRegistry())

    with pytest.raises(TypeError):
        plugin_registry.register_tool(_NoRiskLevelTool())


def test_register_tool_rejects_non_tool_instance():
    plugin_registry = PluginRegistry(ToolRegistry())

    with pytest.raises(TypeError):
        plugin_registry.register_tool("not a tool")  # type: ignore[arg-type]


def test_register_tool_duplicate_name_raises():
    tool_registry = ToolRegistry()
    tool_registry.register(_OkTool())
    plugin_registry = PluginRegistry(tool_registry)

    with pytest.raises(ValueError):
        plugin_registry.register_tool(_OkTool())


def test_register_and_get_reflection_generator():
    plugin_registry = PluginRegistry(ToolRegistry())
    generator = DeterministicReflectionGenerator()

    plugin_registry.register_reflection_generator("det", generator)

    assert plugin_registry.get_reflection_generator("det") is generator
    assert plugin_registry.get_reflection_generator("missing") is None


def test_register_reflection_generator_rejects_wrong_type():
    plugin_registry = PluginRegistry(ToolRegistry())

    with pytest.raises(TypeError):
        plugin_registry.register_reflection_generator("bad", object())  # type: ignore[arg-type]


def test_register_and_get_model_router():
    plugin_registry = PluginRegistry(ToolRegistry())
    router = _StubModelRouter()

    plugin_registry.register_model_router("stub", router)

    assert plugin_registry.get_model_router("stub") is router
    assert plugin_registry.get_model_router("missing") is None


def test_register_model_router_rejects_wrong_type():
    plugin_registry = PluginRegistry(ToolRegistry())

    with pytest.raises(TypeError):
        plugin_registry.register_model_router("bad", object())  # type: ignore[arg-type]
