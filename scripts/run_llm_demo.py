"""First real LLM integration end-to-end demo: model routing (already
config-driven since Phase 4), reflection generation, one-shot task
planning, and curiosity question generation, all backed by Anthropic
Claude when ANTHROPIC_API_KEY is configured — and gracefully explained
when it isn't.

Run this script twice in your development: once before adding a real key
to .env (proves nothing crashes and the deterministic fallback path is
exercised), and once after (proves all 3 LLM swap-points + cost/token
tracking work for real against the live API).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import partial

from megachud.analytics.report import build_analytics_report
from megachud.config import Settings
from megachud.curiosity.engine import CuriosityHandler
from megachud.curiosity.llm_generator import LLMCuriosityTextGenerator
from megachud.db import ensure_agent_project_columns, get_engine, get_or_create_agent, init_db, make_session_factory
from megachud.evaluation.checks import check_python_syntax, check_tests_pass, check_tool_calls_succeeded
from megachud.evaluation.engine import EvaluationEngine
from megachud.events.bus import EventBus
from megachud.events.dispatcher import EventDispatcher
from megachud.events.logger import EventLogger
from megachud.llm.client import AnthropicLLMClient
from megachud.memory.store import MemoryStore
from megachud.models.curiosity import PendingQuestion
from megachud.models.event import Event
from megachud.models.reflection import Reflection
from megachud.models.task import Task
from megachud.obsidian.vault import VaultWriter
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.orchestrator.engine import Orchestrator
from megachud.orchestrator.llm_planner import LLMTaskPlanner
from megachud.reflection.engine import ReflectionEngine
from megachud.reflection.handler import TaskCompletionHandler
from megachud.reflection.llm_generator import LLMReflectionGenerator
from megachud.routing.engine import ModelProfile
from megachud.strategy.metrics import StrategyMetricsHandler
from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry


def build(settings: Settings):
    engine = get_engine(settings.db_path)
    init_db(engine)
    ensure_agent_project_columns(engine)
    session_factory = make_session_factory(engine)

    bus = EventBus()
    agent_id = get_or_create_agent(session_factory, settings.agent_name)

    registry = ToolRegistry()
    registry.register(ReadFileTool(settings.workspace_root))
    registry.register(WriteFileTool(settings.workspace_root))

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

    plain_event_logger = EventLogger(session_factory, bus)

    llm_client = None
    if settings.anthropic_api_key:
        llm_client = AnthropicLLMClient(settings.anthropic_api_key.get_secret_value(), timeout_seconds=settings.llm.timeout_seconds)

    reflection_generator = None
    if llm_client is not None:
        reflection_generator = LLMReflectionGenerator(
            llm_client, model=settings.llm.default_reflection_model, profiles=model_profiles,
            max_tokens=settings.llm.reflection_max_tokens, event_logger=plain_event_logger,
        )

    llm_task_planner = (
        LLMTaskPlanner(llm_client, registry, model=settings.llm.default_planner_model, max_tokens=settings.llm.planner_max_tokens)
        if llm_client is not None else None
    )
    curiosity_text_generator = (
        LLMCuriosityTextGenerator(llm_client, model=settings.llm.default_curiosity_model, max_tokens=settings.llm.curiosity_max_tokens)
        if llm_client is not None else None
    )

    reflection_engine = ReflectionEngine(session_factory, generator=reflection_generator)
    memory_store = MemoryStore(session_factory, vector_dim=settings.memory.vector_dim, agent_id=agent_id, project_name=settings.project_name)
    vault_writer = VaultWriter(settings.vault_root)
    completion_handler = TaskCompletionHandler(reflection_engine, memory_store, vault_writer)
    strategy_metrics_handler = StrategyMetricsHandler(session_factory)
    curiosity_handler = CuriosityHandler(
        session_factory, vector_dim=settings.memory.vector_dim,
        similarity_threshold=settings.curiosity.similarity_threshold,
        research_objective_top_k=settings.curiosity.research_objective_top_k,
        text_generator=curiosity_text_generator, event_logger=plain_event_logger, profiles=model_profiles,
    )
    dispatcher = EventDispatcher([completion_handler, strategy_metrics_handler, curiosity_handler])
    event_logger = EventLogger(session_factory, bus, on_event=dispatcher)

    approval_gate = ApprovalGate(
        session_factory, event_logger,
        timeout_seconds=settings.approval.timeout_seconds, poll_interval_seconds=settings.approval.poll_interval_seconds,
    )
    evaluator = EvaluationEngine(
        checks=[check_tool_calls_succeeded, check_python_syntax, partial(check_tests_pass, test_command=None)]
    )
    orchestrator = Orchestrator(
        session_factory=session_factory, tool_registry=registry, approval_gate=approval_gate,
        evaluator=evaluator, event_logger=event_logger, workspace_root=settings.workspace_root,
    )

    return session_factory, event_logger, orchestrator, llm_task_planner, agent_id


def run_not_configured(session_factory, event_logger, orchestrator, agent_id, settings) -> None:
    print(
        "No ANTHROPIC_API_KEY found (neither in the environment nor in .env) — "
        "falling back to deterministic implementations for reflection/curiosity; "
        "auto-plan (LLMTaskPlanner) is unavailable. Running one task through the "
        "fully-local deterministic path to prove nothing crashes."
    )
    session = session_factory()
    try:
        task = Task(
            title="llm demo (no key): deterministic path",
            prompt="write a greeting file",
            plan_json=json.dumps([{"tool_name": "write_file", "args": {"path": "llm_demo.txt", "content": "hello"}}]),
            agent_id=agent_id, project_name=settings.project_name,
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
        reflection = session.query(Reflection).filter_by(task_id=task_id).first()
        print(f"Reflection produced (deterministic): what_worked={json.loads(reflection.what_worked)}")
    finally:
        session.close()


def run_configured(session_factory, event_logger, orchestrator, llm_task_planner, agent_id, settings) -> None:
    print("ANTHROPIC_API_KEY is configured — running the full LLM-backed pipeline for real.")

    prompt = "Write a short haiku about autonomous software agents to a file named haiku.txt."
    plan_result = llm_task_planner.plan(prompt)
    print(f"\n--- LLM-produced plan ({plan_result.model}, {plan_result.tokens_input}+{plan_result.tokens_output} tokens) ---")
    for step in plan_result.plan:
        print(f"  {step.tool_name}({step.args})")

    session = session_factory()
    try:
        task = Task(
            title="llm demo (configured): auto-planned task", prompt=prompt,
            plan_json=json.dumps([{"tool_name": c.tool_name, "args": c.args} for c in plan_result.plan]),
            agent_id=agent_id, project_name=settings.project_name,
        )
        session.add(task)
        session.commit()
        task_id = task.id
    finally:
        session.close()

    event_logger.log(
        event_type="llm_call", task_id=task_id, tool_name="llm:planner",
        tokens_input=plan_result.tokens_input, tokens_output=plan_result.tokens_output,
        payload={"model": plan_result.model, "consumer": "planner"},
    )

    finished = orchestrator.run_task(task_id)
    print(f"\nTask status: {finished.status.value}")

    session = session_factory()
    try:
        reflection = session.query(Reflection).filter_by(task_id=task_id).order_by(Reflection.id.desc()).first()
        print(f"\n--- Reflection (LLM-backed) ---\nwhat_worked={json.loads(reflection.what_worked)}")

        question = session.query(PendingQuestion).filter_by(source_task_id=task_id).first()
        if question is not None:
            print(f"\n--- Curiosity question (LLM-backed) ---\n{question.question}")
        else:
            print("\n--- Curiosity ---\nno pending question raised (a close prior memory already existed, or this reflection wasn't flagged become_long_term_knowledge)")

        llm_events = session.query(Event).filter_by(event_type="llm_call").order_by(Event.id.desc()).limit(5).all()
        print("\n--- Recent llm_call events ---")
        for e in llm_events:
            print(f"  {e.tool_name}: cost_usd={e.cost_usd} tokens_input={e.tokens_input} tokens_output={e.tokens_output}")
    finally:
        session.close()

    now = datetime.now(timezone.utc)
    report = build_analytics_report(session_factory, now - timedelta(hours=1), now)
    print(f"\n--- Analytics (last 1h) ---\ncost_data_available={report.cost_data_available} total_cost_usd={report.total_cost_usd}")


def main() -> None:
    settings = Settings.load()
    session_factory, event_logger, orchestrator, llm_task_planner, agent_id = build(settings)

    if llm_task_planner is None:
        run_not_configured(session_factory, event_logger, orchestrator, agent_id, settings)
    else:
        run_configured(session_factory, event_logger, orchestrator, llm_task_planner, agent_id, settings)


if __name__ == "__main__":
    main()
