"""Phase 5 end-to-end demo: plugin loading + a real task run through a
plugin-registered tool, plus agent/project identity tagging.

Unlike run_optimization_demo.py (read-only), this needs the full
orchestrator/tool stack, since the single highest-value thing to prove
for real (not just unit-tested) is that a plugin's Tool actually executes
through Orchestrator.run_task with zero special-casing — the approval
gate already applies uniformly regardless of a tool's origin.
"""

from __future__ import annotations

import json
from functools import partial

from megachud.config import PluginsConfig, Settings
from megachud.db import ensure_agent_project_columns, get_engine, get_or_create_agent, init_db, make_session_factory
from megachud.evaluation.checks import check_python_syntax, check_tests_pass, check_tool_calls_succeeded
from megachud.evaluation.engine import EvaluationEngine
from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.agent import Agent
from megachud.models.event import Event
from megachud.models.task import Task
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.orchestrator.engine import Orchestrator
from megachud.plugins.loader import load_plugins
from megachud.plugins.registry import PluginRegistry
from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry


def main() -> None:
    settings = Settings.load()
    # Force-enable the shipped example plugin for this demo, regardless of
    # config/local.yaml's state, so the script is self-contained and
    # reproducible on a fresh clone.
    settings = settings.model_copy(update={"plugins": PluginsConfig(enabled_local=["example_uppercase"])})

    engine = get_engine(settings.db_path)
    init_db(engine)
    ensure_agent_project_columns(engine)
    session_factory = make_session_factory(engine)

    bus = EventBus()
    agent_id = get_or_create_agent(session_factory, settings.agent_name)
    print(f"Agent: {settings.agent_name} ({agent_id})")
    print(f"Project: {settings.project_name}")

    registry = ToolRegistry()
    registry.register(ReadFileTool(settings.workspace_root))
    registry.register(WriteFileTool(settings.workspace_root))

    plugin_registry = PluginRegistry(registry)
    results = load_plugins(settings, plugin_registry, EventLogger(session_factory, bus))
    print("\n--- Plugin Load Results ---")
    for r in results:
        status = "OK" if r.success else f"FAILED: {r.error}"
        print(f"{r.name} ({r.source}): {status}")

    event_logger = EventLogger(session_factory, bus)
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

    print("\n--- Running a task through the plugin-registered tool ---")
    session = session_factory()
    try:
        task = Task(
            title="platform demo: uppercase via plugin",
            prompt="prove a plugin tool executes through the real orchestrator",
            plan_json=json.dumps([{"tool_name": "uppercase_text", "args": {"text": "phase 5 works"}}]),
            agent_id=agent_id,
            project_name=settings.project_name,
        )
        session.add(task)
        session.commit()
        task_id = task.id
    finally:
        session.close()

    finished = orchestrator.run_task(task_id)
    print(f"Task status: {finished.status.value}")

    session = session_factory()
    try:
        tool_result = session.query(Event).filter_by(task_id=task_id, event_type="tool_result").first()
        print(f"Tool output: {json.loads(tool_result.payload_json)['output']}")
    finally:
        session.close()

    print("\n--- Agents ---")
    session = session_factory()
    try:
        for a in session.query(Agent).all():
            print(f"{a.name}: {a.id}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
