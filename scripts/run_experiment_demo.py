"""Phase 3 end-to-end demo, built incrementally across all 6 build steps.

Step 3 (this version): seed a "variant" strategy that always succeeds
(appends .txt instead of trusting the caller's extension), run enough
invocations of both control and variant to clear the experiment's
minimum sample size, then evaluate the experiment and show the resulting
recommendation + PromotionRequest.
"""

import json
from functools import partial

from megachud.config import Settings
from megachud.db import get_engine, init_db, make_session_factory
from megachud.evaluation.checks import check_python_syntax, check_tests_pass, check_tool_calls_succeeded
from megachud.evaluation.engine import EvaluationEngine
from megachud.events.bus import EventBus
from megachud.events.dispatcher import EventDispatcher
from megachud.events.logger import EventLogger
from megachud.experiment.engine import evaluate_experiment
from megachud.memory.store import MemoryStore
from megachud.models.experiment import Experiment
from megachud.models.promotion_request import PromotionRequest
from megachud.models.strategy import Strategy, StrategyOrigin
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

WORKFLOW_NAME = "write_greeting"
# Hardcoded here rather than read from settings.experiment.default_minimum_sample_size
# — that config key doesn't exist until Step 6.
MIN_SAMPLES = 5


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


def seed_variant_strategy(session_factory, control_id: str) -> str:
    session = session_factory()
    try:
        existing = (
            session.query(Strategy)
            .filter_by(workflow_name=WORKFLOW_NAME, origin=StrategyOrigin.EXPERIMENT_VARIANT)
            .first()
        )
        if existing is not None:
            return existing.id

        variant = Strategy(
            workflow_name=WORKFLOW_NAME,
            version=2,
            is_active=False,
            title="Write a greeting file (always .txt)",
            description="Same as control but always appends .txt, so the syntax check never applies.",
            plan_template_json=json.dumps(
                [{"tool_name": "write_file", "args": {"path": "{filename}.txt", "content": "Hello, {name}!"}}]
            ),
            parameters_json=json.dumps(["filename", "name"]),
            tags_json=json.dumps(["file_io", "demo", "variant"]),
            origin=StrategyOrigin.EXPERIMENT_VARIANT,
            parent_strategy_id=control_id,
        )
        session.add(variant)
        session.commit()
        return variant.id
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


def create_experiment(session_factory, control_id: str, variant_id: str, min_samples: int) -> str:
    session = session_factory()
    try:
        experiment = Experiment(
            workflow_name=WORKFLOW_NAME,
            hypothesis="Always writing .txt avoids the syntax-check failures the control strategy hits.",
            control_strategy_id=control_id,
            variant_strategy_id=variant_id,
            minimum_sample_size=min_samples,
        )
        session.add(experiment)
        session.commit()
        return experiment.id
    finally:
        session.close()


def main() -> None:
    settings = Settings.load()
    session_factory, event_logger, orchestrator = build(settings)

    strategy_id = seed_strategy(session_factory)
    variant_id = seed_variant_strategy(session_factory, strategy_id)
    print(f"Control strategy: {strategy_id}")
    print(f"Variant strategy: {variant_id}")

    success_task = invoke_and_run(session_factory, event_logger, orchestrator, strategy_id, {"filename": "greeting.txt", "name": "MegaChud"})
    print(f"Run 1 (control, greeting.txt): status={success_task.status.value}")

    failure_task = invoke_and_run(session_factory, event_logger, orchestrator, strategy_id, {"filename": "broken.py", "name": "MegaChud"})
    print(f"Run 2 (control, broken.py, invalid syntax): status={failure_task.status.value}")

    print_strategy_metrics(session_factory, strategy_id, "Control after 2 runs")

    min_samples = MIN_SAMPLES
    print(f"\nRunning {min_samples} more invocations of each strategy to clear minimum_sample_size={min_samples}...")
    for i in range(min_samples):
        # Control alternates safe/unsafe extensions -> ~50% success rate.
        ext = "txt" if i % 2 == 0 else "py"
        invoke_and_run(session_factory, event_logger, orchestrator, strategy_id, {"filename": f"c{i}.{ext}", "name": "x"})
        # Variant always appends .txt itself -> always succeeds.
        invoke_and_run(session_factory, event_logger, orchestrator, variant_id, {"filename": f"v{i}", "name": "x"})

    print_strategy_metrics(session_factory, strategy_id, "Control final")
    print_strategy_metrics(session_factory, variant_id, "Variant final")

    experiment_id = create_experiment(session_factory, strategy_id, variant_id, min_samples)
    result = evaluate_experiment(session_factory, experiment_id)
    print(f"\nExperiment {experiment_id}: status={result.status.value} recommendation={result.recommendation.value}")
    print(f"result_json: {result.result_json}")

    session = session_factory()
    try:
        request = session.query(PromotionRequest).filter_by(experiment_id=experiment_id).first()
        if request is not None:
            print(f"PromotionRequest {request.id}: {request.workflow_name} -> promote to {request.to_strategy_id}")
            print(f"  justification: {request.justification}")
        else:
            print("No PromotionRequest created.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
