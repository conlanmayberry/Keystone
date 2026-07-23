from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from megachud.api import (
    routes_agents,
    routes_analytics,
    routes_approvals,
    routes_bottleneck,
    routes_conversations,
    routes_curiosity,
    routes_experiment,
    routes_memory,
    routes_meta,
    routes_plugins,
    routes_promotion,
    routes_prompts,
    routes_review,
    routes_routing,
    routes_status,
    routes_strategy,
    routes_tasks,
    ws,
)
from megachud.config import Settings
from megachud.conversation.engine import ConversationEngine
from megachud.conversation.prompt_drafter import PromptDrafter
from megachud.curiosity.engine import CuriosityHandler
from megachud.curiosity.llm_generator import LLMCuriosityTextGenerator
from megachud.db import (
    ensure_agent_project_columns,
    ensure_task_execution_mode_column,
    get_engine,
    get_or_create_agent,
    init_db,
    make_session_factory,
)
from megachud.evaluation.checks import check_python_syntax, check_tests_pass, check_tool_calls_succeeded
from megachud.evaluation.engine import EvaluationEngine
from megachud.events.bus import EventBus
from megachud.events.dispatcher import EventDispatcher
from megachud.events.logger import EventLogger
from megachud.llm.client import AnthropicLLMClient, LLMClient
from megachud.memory.store import MemoryStore
from megachud.obsidian.vault import VaultWriter
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.orchestrator.engine import Orchestrator
from megachud.orchestrator.llm_planner import LLMTaskPlanner
from megachud.plugins.loader import load_plugins
from megachud.plugins.registry import PluginRegistry
from megachud.reflection.engine import ReflectionEngine
from megachud.reflection.handler import TaskCompletionHandler
from megachud.reflection.llm_generator import LLMReflectionGenerator
from megachud.routing.engine import ConfiguredModelRouter, ModelProfile
from megachud.routing.selector import ModelSelector
from megachud.runtime.activity import ActivityTracker
from megachud.runtime.thoughts import ThoughtLog
from megachud.strategy.metrics import StrategyMetricsHandler
from megachud.browser.cleanup import BrowserSessionCleanupHandler
from megachud.browser.session import BrowserSessionManager
from megachud.tools.browser_tools import (
    BrowserClickTool,
    BrowserFillTool,
    BrowserNavigateTool,
    BrowserReadTool,
    BrowserSubmitTool,
)
from megachud.tools.file_tools import (
    AppendFileTool,
    ListDirectoryTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from megachud.tools.internet_tools import DownloadFileTool, ExtractTextTool, HttpFetchTool
from megachud.tools.registry import ToolRegistry
from megachud.tools.shell_tool import ShellExecTool
from megachud.tools.web_search_tool import WebSearchTool

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()

    engine = get_engine(settings.db_path)
    init_db(engine)
    ensure_agent_project_columns(engine)
    ensure_task_execution_mode_column(engine)
    session_factory = make_session_factory(engine)

    bus = EventBus()
    current_agent_id = get_or_create_agent(session_factory, settings.agent_name)

    # Live runtime state (in-memory, ephemeral). Created early so the
    # background reflection/curiosity components can record thoughts too.
    activity = ActivityTracker()
    thought_log = ThoughtLog(
        max_entries=settings.runtime.thought_max_entries, max_chars=settings.runtime.thought_max_chars
    )

    # Build the default (non-plugin) tool set first, so plugin loading can
    # only add to an already-valid baseline.
    registry = ToolRegistry()
    registry.register(ReadFileTool(settings.workspace_root))
    registry.register(WriteFileTool(settings.workspace_root))
    registry.register(AppendFileTool(settings.workspace_root))
    registry.register(ListDirectoryTool(settings.workspace_root))
    registry.register(SearchFilesTool(settings.workspace_root))
    registry.register(
        ShellExecTool(
            settings.workspace_root,
            allowlist=settings.shell.allowlist,
            denylist=settings.shell.denylist,
            timeout_seconds=settings.shell.timeout_seconds,
        )
    )
    registry.register(
        HttpFetchTool(
            max_response_bytes=settings.internet.fetch.max_response_bytes,
            timeout_seconds=settings.internet.fetch.timeout_seconds,
            max_redirects=settings.internet.fetch.max_redirects,
            domain_allowlist=settings.internet.domain_allowlist,
            domain_denylist=settings.internet.domain_denylist,
        )
    )
    registry.register(
        ExtractTextTool(
            max_response_bytes=settings.internet.fetch.max_response_bytes,
            timeout_seconds=settings.internet.fetch.timeout_seconds,
            max_redirects=settings.internet.fetch.max_redirects,
            domain_allowlist=settings.internet.domain_allowlist,
            domain_denylist=settings.internet.domain_denylist,
        )
    )
    registry.register(
        DownloadFileTool(
            settings.workspace_root,
            max_file_bytes=settings.internet.download.max_file_bytes,
            max_folder_bytes=settings.internet.download.max_folder_bytes,
            blocked_extensions=settings.internet.download.blocked_extensions,
            timeout_seconds=settings.internet.download.timeout_seconds,
            max_redirects=settings.internet.download.max_redirects,
            domain_allowlist=settings.internet.domain_allowlist,
            domain_denylist=settings.internet.domain_denylist,
        )
    )
    if settings.brave_api_key:
        registry.register(
            WebSearchTool(
                settings.brave_api_key.get_secret_value(),
                max_results=settings.internet.search.max_results,
                timeout_seconds=settings.internet.search.timeout_seconds,
            )
        )

    # Browser automation (Stage B). The manager lazily launches Playwright
    # on first use — registration is unconditional and never launches a
    # browser, so create_app() stays side-effect-free and doesn't require
    # playwright/chromium to be installed (the tools fail gracefully if
    # they aren't). Read-only tools here; interaction tools in Step 2.
    browser_manager = BrowserSessionManager(
        headless=settings.internet.browser.headless,
        nav_timeout_ms=settings.internet.browser.nav_timeout_ms,
        max_sessions=settings.internet.browser.max_sessions,
        viewport=(settings.internet.browser.viewport_width, settings.internet.browser.viewport_height),
    )
    registry.register(
        BrowserNavigateTool(
            browser_manager,
            domain_allowlist=settings.internet.domain_allowlist,
            domain_denylist=settings.internet.domain_denylist,
        )
    )
    registry.register(BrowserReadTool(browser_manager))
    registry.register(BrowserFillTool(browser_manager))
    registry.register(
        BrowserClickTool(
            browser_manager,
            state_changing_button_text=settings.internet.browser.state_changing_button_text,
        )
    )
    registry.register(BrowserSubmitTool(browser_manager))

    model_profiles = [
        ModelProfile(
            name=p.name,
            cost_per_1k_input_tokens=p.cost_per_1k_input_tokens,
            cost_per_1k_output_tokens=p.cost_per_1k_output_tokens,
            quality_tier=p.quality_tier,
            est_latency_ms=p.est_latency_ms,
        )
        for p in settings.model_routing.profiles
    ]
    default_model_router = ConfiguredModelRouter(model_profiles)

    # Dispatch-free EventLogger — used for events that are pure logging,
    # not decisions that should trigger the reflection/curiosity/strategy-
    # metrics pipeline: plugin load results and llm_call cost events.
    plain_event_logger = EventLogger(session_factory, bus)

    plugin_registry = PluginRegistry(registry)
    plugin_load_results = load_plugins(settings, plugin_registry, plain_event_logger)

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

    # LLM components: every one of them is conditionally None when no key
    # is configured — create_app() must not raise or behave differently
    # for anyone who hasn't set ANTHROPIC_API_KEY. Only fills in an
    # LLM-backed reflection_generator if no plugin already claimed that
    # swap-point.
    llm_client: LLMClient | None = None
    if settings.anthropic_api_key:
        llm_client = AnthropicLLMClient(
            settings.anthropic_api_key.get_secret_value(), timeout_seconds=settings.llm.timeout_seconds
        )

    if reflection_generator is None and llm_client is not None:
        reflection_generator = LLMReflectionGenerator(
            llm_client,
            model=settings.llm.default_reflection_model,
            profiles=model_profiles,
            max_tokens=settings.llm.reflection_max_tokens,
            event_logger=plain_event_logger,
            thought_log=thought_log,
        )

    # One shared selector: manual override wins, else a heuristic escalates
    # tier for complex/long prompts. Only the two interactive consumers
    # (planner, conversation) use it — background cheap consumers keep their
    # fixed defaults by design.
    planner_selector = ModelSelector(model_profiles, default_model=settings.llm.default_planner_model)
    conversation_selector = ModelSelector(model_profiles, default_model=settings.llm.default_conversation_model)

    llm_task_planner = (
        LLMTaskPlanner(
            llm_client,
            registry,
            model=settings.llm.default_planner_model,
            max_tokens=settings.llm.planner_max_tokens,
            selector=planner_selector,
        )
        if llm_client is not None
        else None
    )

    conversation_engine = (
        ConversationEngine(
            llm_client,
            registry,
            model=settings.llm.default_conversation_model,
            max_tokens=settings.llm.conversation_max_tokens,
            selector=conversation_selector,
        )
        if llm_client is not None
        else None
    )

    prompt_drafter = (
        PromptDrafter(
            llm_client,
            model=settings.llm.default_prompt_drafter_model,
            max_tokens=settings.llm.prompt_drafter_max_tokens,
        )
        if llm_client is not None
        else None
    )

    curiosity_text_generator = (
        LLMCuriosityTextGenerator(
            llm_client, model=settings.llm.default_curiosity_model, max_tokens=settings.llm.curiosity_max_tokens
        )
        if llm_client is not None
        else None
    )

    reflection_engine = ReflectionEngine(session_factory, generator=reflection_generator)
    memory_store = MemoryStore(
        session_factory,
        vector_dim=settings.memory.vector_dim,
        agent_id=current_agent_id,
        project_name=settings.project_name,
    )
    vault_writer = VaultWriter(settings.vault_root)
    completion_handler = TaskCompletionHandler(reflection_engine, memory_store, vault_writer)
    strategy_metrics_handler = StrategyMetricsHandler(session_factory)
    curiosity_handler = CuriosityHandler(
        session_factory,
        vector_dim=settings.memory.vector_dim,
        similarity_threshold=settings.curiosity.similarity_threshold,
        research_objective_top_k=settings.curiosity.research_objective_top_k,
        text_generator=curiosity_text_generator,
        event_logger=plain_event_logger,
        profiles=model_profiles,
        thought_log=thought_log,
    )

    # Order matters: completion_handler must run first — curiosity_handler
    # reads the Reflection row it creates. The browser cleanup handler runs
    # LAST, so nothing that still reads task state runs after teardown.
    dispatcher = EventDispatcher(
        [
            completion_handler,
            strategy_metrics_handler,
            curiosity_handler,
            BrowserSessionCleanupHandler(browser_manager),
        ]
    )
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
        browser_manager.close_all()

    app = FastAPI(title="MegaChud", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.event_bus = bus
    app.state.event_logger = event_logger
    app.state.approval_gate = approval_gate
    app.state.orchestrator = orchestrator
    app.state.tool_registry = registry
    app.state.browser_manager = browser_manager
    app.state.memory_store = memory_store
    app.state.vault_writer = vault_writer
    app.state.model_router = model_router
    app.state.model_profiles = model_profiles
    app.state.plugin_load_results = plugin_load_results
    app.state.current_agent_id = current_agent_id
    app.state.llm_client = llm_client
    app.state.llm_task_planner = llm_task_planner
    app.state.conversation_engine = conversation_engine
    app.state.prompt_drafter = prompt_drafter
    app.state.activity = activity
    app.state.thought_log = thought_log
    app.state.executor = ThreadPoolExecutor(max_workers=4)

    app.include_router(routes_tasks.router)
    app.include_router(routes_conversations.router)
    app.include_router(routes_prompts.router)
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
    app.include_router(routes_status.router)
    app.include_router(routes_agents.router)
    app.include_router(routes_meta.router)
    app.include_router(routes_plugins.router)
    app.include_router(ws.router)

    # No caching for the dashboard's own JS/CSS/HTML: without this, a
    # browser can silently keep running a stale cached app.js after a code
    # change + server restart, with no visible error — exactly the
    # confusing "nothing happens when I click" symptom that motivated this.
    # These files are tiny and served locally, so there's no real
    # performance cost to always revalidating.
    @app.middleware("http")
    async def no_cache_static(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

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
