from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from megachud.api import (
    routes_analytics,
    routes_approvals,
    routes_bottleneck,
    routes_curiosity,
    routes_experiment,
    routes_memory,
    routes_promotion,
    routes_review,
    routes_routing,
    routes_strategy,
    routes_tasks,
    ws,
)
from megachud.config import Settings
from megachud.curiosity.engine import CuriosityHandler
from megachud.db import ensure_agent_project_columns, get_engine, get_or_create_agent, init_db, make_session_factory
from megachud.evaluation.checks import check_python_syntax, check_tests_pass, check_tool_calls_succeeded
from megachud.evaluation.engine import EvaluationEngine
from megachud.events.bus import EventBus
from megachud.events.dispatcher import EventDispatcher
from megachud.events.logger import EventLogger
from megachud.memory.store import MemoryStore
from megachud.obsidian.vault import VaultWriter
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.orchestrator.engine import Orchestrator
from megachud.plugins.loader import load_plugins
from megachud.plugins.registry import PluginRegistry
from megachud.reflection.engine import ReflectionEngine
from megachud.reflection.handler import TaskCompletionHandler
from megachud.routing.engine import ConfiguredModelRouter, ModelProfile
from megachud.strategy.metrics import StrategyMetricsHandler
from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry
from megachud.tools.shell_tool import ShellExecTool

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()

    engine = get_engine(settings.db_path)
    init_db(engine)
    ensure_agent_project_columns(engine)
    session_factory = make_session_factory(engine)

    bus = EventBus()
    current_agent_id = get_or_create_agent(session_factory, settings.agent_name)

    # Build the default (non-plugin) tool set first, so plugin loading can
    # only add to an already-valid baseline.
    registry = ToolRegistry()
    registry.register(ReadFileTool(settings.workspace_root))
    registry.register(WriteFileTool(settings.workspace_root))
    registry.register(
        ShellExecTool(
            settings.workspace_root,
            allowlist=settings.shell.allowlist,
            denylist=settings.shell.denylist,
            timeout_seconds=settings.shell.timeout_seconds,
        )
    )

    default_model_router = ConfiguredModelRouter(
        [
            ModelProfile(
                name=p.name,
                cost_per_1k_input_tokens=p.cost_per_1k_input_tokens,
                cost_per_1k_output_tokens=p.cost_per_1k_output_tokens,
                quality_tier=p.quality_tier,
                est_latency_ms=p.est_latency_ms,
            )
            for p in settings.model_routing.profiles
        ]
    )

    # Plugin loading gets its own simple EventLogger — plugin_load events
    # are pure logging, not decisions that should trigger the reflection/
    # curiosity/strategy-metrics pipeline, so they don't need on_event.
    plugin_registry = PluginRegistry(registry)
    plugin_load_results = load_plugins(settings, plugin_registry, EventLogger(session_factory, bus))

    reflection_generator = (
        plugin_registry.get_reflection_generator(settings.plugins.active_reflection_generator)
        if settings.plugins.active_reflection_generator
        else None
    )
    model_router = (
        plugin_registry.get_model_router(settings.plugins.active_model_router)
        if settings.plugins.active_model_router
        else default_model_router
    )

    reflection_engine = ReflectionEngine(session_factory, generator=reflection_generator)
    memory_store = MemoryStore(session_factory, vector_dim=settings.memory.vector_dim)
    vault_writer = VaultWriter(settings.vault_root)
    completion_handler = TaskCompletionHandler(reflection_engine, memory_store, vault_writer)
    strategy_metrics_handler = StrategyMetricsHandler(session_factory)
    curiosity_handler = CuriosityHandler(
        session_factory,
        vector_dim=settings.memory.vector_dim,
        similarity_threshold=settings.curiosity.similarity_threshold,
        research_objective_top_k=settings.curiosity.research_objective_top_k,
    )

    # Order matters: completion_handler must run first — curiosity_handler
    # reads the Reflection row it creates.
    dispatcher = EventDispatcher([completion_handler, strategy_metrics_handler, curiosity_handler])
    event_logger = EventLogger(session_factory, bus, on_event=dispatcher)

    approval_gate = ApprovalGate(
        session_factory,
        event_logger,
        timeout_seconds=settings.approval.timeout_seconds,
        poll_interval_seconds=settings.approval.poll_interval_seconds,
    )

    evaluator = EvaluationEngine(
        checks=[
            check_tool_calls_succeeded,
            check_python_syntax,
            partial(check_tests_pass, test_command=settings.evaluation.test_command),
        ]
    )

    orchestrator = Orchestrator(
        session_factory=session_factory,
        tool_registry=registry,
        approval_gate=approval_gate,
        evaluator=evaluator,
        event_logger=event_logger,
        workspace_root=settings.workspace_root,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        bus.bind_loop(asyncio.get_running_loop())
        yield
        app.state.executor.shutdown(wait=False)

    app = FastAPI(title="MegaChud", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.event_bus = bus
    app.state.event_logger = event_logger
    app.state.approval_gate = approval_gate
    app.state.orchestrator = orchestrator
    app.state.tool_registry = registry
    app.state.memory_store = memory_store
    app.state.vault_writer = vault_writer
    app.state.model_router = model_router
    app.state.plugin_load_results = plugin_load_results
    app.state.current_agent_id = current_agent_id
    app.state.executor = ThreadPoolExecutor(max_workers=4)

    app.include_router(routes_tasks.router)
    app.include_router(routes_approvals.router)
    app.include_router(routes_memory.router)
    app.include_router(routes_strategy.router)
    app.include_router(routes_experiment.router)
    app.include_router(routes_promotion.router)
    app.include_router(routes_curiosity.router)
    app.include_router(routes_bottleneck.router)
    app.include_router(routes_analytics.router)
    app.include_router(routes_review.router)
    app.include_router(routes_routing.router)
    app.include_router(ws.router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


# No module-level `app = create_app()` here on purpose: importing this
# module (e.g. from tests, which want an isolated test-settings app) would
# otherwise eagerly instantiate an app against the real dev DB as a side
# effect of import. Run the dev server via uvicorn's factory pattern:
#   uvicorn megachud.api.app:create_app --factory --reload
