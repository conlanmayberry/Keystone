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

from megachud.api import routes_approvals, routes_tasks, ws
from megachud.config import Settings
from megachud.db import get_engine, init_db, make_session_factory
from megachud.evaluation.checks import check_python_syntax, check_tests_pass, check_tool_calls_succeeded
from megachud.evaluation.engine import EvaluationEngine
from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.memory.store import MemoryStore
from megachud.obsidian.vault import VaultWriter
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.orchestrator.engine import Orchestrator
from megachud.reflection.engine import ReflectionEngine
from megachud.reflection.handler import TaskCompletionHandler
from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry
from megachud.tools.shell_tool import ShellExecTool

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()

    engine = get_engine(settings.db_path)
    init_db(engine)
    session_factory = make_session_factory(engine)

    bus = EventBus()

    reflection_engine = ReflectionEngine(session_factory)
    memory_store = MemoryStore(session_factory, vector_dim=settings.memory.vector_dim)
    vault_writer = VaultWriter(settings.vault_root)
    completion_handler = TaskCompletionHandler(reflection_engine, memory_store, vault_writer)

    event_logger = EventLogger(session_factory, bus, on_event=completion_handler)

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
    app.state.executor = ThreadPoolExecutor(max_workers=4)

    app.include_router(routes_tasks.router)
    app.include_router(routes_approvals.router)
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
