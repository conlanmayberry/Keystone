"""Phase 3 end-to-end demo, built incrementally across all 6 build steps.

Step 2 (this version): run the invoked task through a real Orchestrator,
wired with EventDispatcher([TaskCompletionHandler, StrategyMetricsHandler])
exactly like api/app.py does, twice with different outcomes — a
successful write and a deliberate Python-syntax-error failure (the
strategy's template writes "Hello, {name}!" as file content, which is
valid text but NOT valid Python; writing it to a .py file trips the
evaluation engine's syntax check) — then prints the Strategy's updated
success_rate/sample_count against the real dev DB.
"""

import json

from megachud.config import Settings
from megachud.db import get_engine, init_db, make_session_factory
from megachud.evaluation.checks import check_python_syntax, check_tests_pass, check_tool_calls_succeeded
from megachud.evaluation.engine import EvaluationEngine
from megachud.events.bus import EventBus
from megachud.events.dispatcher import EventDispatcher
from megachud.events.logger import EventLogger
from megachud.memory.store import MemoryStore
from megachud.models.strategy import Strategy
from megachud.models.task import Task
from megachud.obsidian.vault import VaultWriter
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.orchestrator.engine import Orchestrator
from megachud.reflection.engine import ReflectionEngine
from megachud.reflection.handler import TaskCompletionHandler
from megachud.strategy.invoker import invoke_strategy
from megachud.strategy.metrics import StrategyMetricsHandler
from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry
from functools import partial

WORKFLOW_NAME = "write_greeting"


def seed_strategy(session_factory) -> str:
    session = session_factory()
    try:
        existing = session.query(Strategy).filter_by(workflow_name=WORKFLOW_NAME, is_active=True).first()
        if existing is not None:
            return existing.id

        strategy = Strategy(
            workflow_name=WORKFLOW_NAME,
            version=1,
            is_active=True,
            title="Write a greeting file",
            description="Writes a short greeting to a text file in the workspace.",
            plan_template_json=json.dumps(
                [{"tool_name": "write_file", "args": {"path": "{filename}", "content": "Hello, {name}!"}}]
            ),
            parameters_json=json.dumps(["filename", "name"]),
            tags_json=json.dumps(["file_io", "demo"]),
        )
        session.add(strategy)
        session.commit()
        return strategy.id
    finally:
        session.close()


def build(settings: Settings):
    engine = get_engine(settings.db_path)
    init_db(engine)
    session_factory = make_session_factory(engine)

    reflection_engine = ReflectionEngine(session_factory)
    memory_store = MemoryStore(session_factory, vector_dim=settings.memory.vector_dim)
    vault_writer = VaultWriter(settings.vault_root)
    completion_handler = TaskCompletionHandler(reflection_engine, memory_store, vault_writer)
    strategy_metrics_handler = StrategyMetricsHandler(session_factory)
    dispatcher = EventDispatcher([completion_handler, strategy_metrics_handler])

    event_logger = EventLogger(session_factory, EventBus(), on_event=dispatcher)

    registry = ToolRegistry()
    registry.register(ReadFileTool(settings.workspace_root))
    registry.register(WriteFileTool(settings.workspace_root))

    approval_gate = ApprovalGate(
        session_factory,
        event_logger,
        timeout_seconds=settings.approval.timeout_seconds,
        poll_interval_seconds=settings.approval.poll_interval_seconds,
    )
    evaluator = EvaluationEngine(
        checks=[check_tool_calls_succeeded, check_python_syntax, partial(check_tests_pass, test_command=None)]
    )
    orchestrator = Orchestrator(
        session_factory=session_factory,
        tool_registry=registry,
        approval_gate=approval_gate,
        evaluator=evaluator,
        event_logger=event_logger,
        workspace_root=settings.workspace_root,
    )
    return session_factory, event_logger, orchestrator


def invoke_and_run(session_factory, event_logger, orchestrator, strategy_id: str, params: dict) -> Task:
    task_id = invoke_strategy(session_factory, strategy_id, params)
    event_logger.log(event_type="strategy_invoked", task_id=task_id, payload={"strategy_id": strategy_id, "params": params})
    return orchestrator.run_task(task_id)


def print_strategy_metrics(session_factory, strategy_id: str, label: str) -> None:
    session = session_factory()
    try:
        strategy = session.get(Strategy, strategy_id)
        print(f"{label}: sample_count={strategy.sample_count} success_count={strategy.success_count} success_rate={strategy.success_rate:.2f}")
    finally:
        session.close()


def main() -> None:
    settings = Settings.load()
    session_factory, event_logger, orchestrator = build(settings)

    strategy_id = seed_strategy(session_factory)
    print(f"Strategy: {strategy_id}")
    print_strategy_metrics(session_factory, strategy_id, "Before")

    success_task = invoke_and_run(session_factory, event_logger, orchestrator, strategy_id, {"filename": "greeting.txt", "name": "MegaChud"})
    print(f"Run 1 (greeting.txt): status={success_task.status.value}")

    failure_task = invoke_and_run(session_factory, event_logger, orchestrator, strategy_id, {"filename": "broken.py", "name": "MegaChud"})
    print(f"Run 2 (broken.py, invalid syntax): status={failure_task.status.value}")

    print_strategy_metrics(session_factory, strategy_id, "After")


if __name__ == "__main__":
    main()
