from __future__ import annotations

from megachud.models.approval import RiskLevel
from megachud.reflection.generator import ReflectionGenerator
from megachud.routing.engine import ModelRouter
from megachud.tools.base import Tool
from megachud.tools.registry import ToolRegistry


class PluginRegistry:
    """Passed into a plugin's `register(registry)` function. Constructed
    with the app's REAL ToolRegistry — register_tool delegates to it
    immediately after risk_level validation, not a parallel/deferred
    registry. This is the single choke point where a plugin-provided
    Tool's risk_level is actually enforced, before it can ever reach
    Orchestrator.run_task's approval-gate check. Once registered, a
    plugin tool is indistinguishable at that gate from a built-in one —
    the approval gate is the real safety boundary for actions, and it
    already applies uniformly regardless of code origin.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry
        self._reflection_generators: dict[str, ReflectionGenerator] = {}
        self._model_routers: dict[str, ModelRouter] = {}

    def register_tool(self, tool: Tool) -> None:
        if not isinstance(tool, Tool) or not isinstance(getattr(tool, "risk_level", None), RiskLevel):
            raise TypeError(f"plugin tool {tool!r} must be a Tool subclass with risk_level set")
        # Reuses ToolRegistry's existing duplicate-name ValueError — a
        # plugin can't silently shadow write_file or another built-in tool.
        self._tool_registry.register(tool)

    def register_reflection_generator(self, name: str, generator: ReflectionGenerator) -> None:
        if not isinstance(generator, ReflectionGenerator):
            raise TypeError(f"plugin reflection generator {generator!r} must be a ReflectionGenerator")
        self._reflection_generators[name] = generator

    def register_model_router(self, name: str, router: ModelRouter) -> None:
        if not isinstance(router, ModelRouter):
            raise TypeError(f"plugin model router {router!r} must be a ModelRouter")
        self._model_routers[name] = router

    def get_reflection_generator(self, name: str) -> ReflectionGenerator | None:
        return self._reflection_generators.get(name)

    def get_model_router(self, name: str) -> ModelRouter | None:
        return self._model_routers.get(name)
