"""Phase 4 end-to-end demo: model routing, analytics, hourly/weekly review.

Unlike run_experiment_demo.py, this script does NOT need the full
orchestrator/tool stack — Phase 4 is read/report-focused (it reports on
tasks that already exist in the dev DB, most of which were created by
prior runs of run_dummy_task.py / run_memory_demo.py / run_experiment_demo.py),
not task-creation-focused. It only needs a session factory and an
EventLogger to log routing decisions.

Run scripts/run_experiment_demo.py at least once first so there's real
Strategy/Task/Reflection data for the analytics/review sections to report
on.
"""

from __future__ import annotations

from megachud.analytics.report import build_analytics_report
from megachud.config import Settings
from megachud.db import get_engine, init_db, make_session_factory
from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.strategy import Strategy
from megachud.review.generator import generate_hourly_review, generate_weekly_review, persist_review
from megachud.routing.engine import ConfiguredModelRouter, ModelProfile
from megachud.routing.logging import log_routing_decision


def build_router(settings: Settings) -> ConfiguredModelRouter:
    profiles = [
        ModelProfile(
            name=p.name,
            cost_per_1k_input_tokens=p.cost_per_1k_input_tokens,
            cost_per_1k_output_tokens=p.cost_per_1k_output_tokens,
            quality_tier=p.quality_tier,
            est_latency_ms=p.est_latency_ms,
        )
        for p in settings.model_routing.profiles
    ]
    return ConfiguredModelRouter(profiles)


def simulate_routing_decisions(session_factory, event_logger, router: ConfiguredModelRouter) -> None:
    print("--- Model Routing Simulation ---")
    session = session_factory()
    try:
        workflow_names = [row[0] for row in session.query(Strategy.workflow_name).distinct().all()]
    finally:
        session.close()

    if not workflow_names:
        workflow_names = ["coding"]

    quality_targets = [1, 2, 3]
    for task_type, quality_target in zip(workflow_names, quality_targets * 2):
        try:
            decision = router.route(task_type, quality_target, est_tokens_input=800, est_tokens_output=400)
        except Exception as exc:  # noqa: BLE001 - NoQualifyingModelError, demo just reports it
            print(f"{task_type} (quality_target={quality_target}): no qualifying model — {exc}")
            continue
        log_routing_decision(event_logger, task_id=None, task_type=task_type, decision=decision)
        print(f"{task_type} (quality_target={quality_target}): chose {decision.chosen_model} — {decision.reason}")


def print_analytics(session_factory) -> None:
    from datetime import datetime, timedelta, timezone

    print("\n--- Analytics (last 24h) ---")
    now = datetime.now(timezone.utc)
    report = build_analytics_report(session_factory, now - timedelta(hours=24), now)
    print(f"task_counts_by_status: {report.task_counts_by_status}")
    print(f"tool_call_counts: {report.tool_call_counts}")
    print(f"tool_failure_rates: {report.tool_failure_rates}")
    print(f"strategy_success_rates: {report.strategy_success_rates}")
    print(f"become_long_term_knowledge_rate: {report.become_long_term_knowledge_rate:.2f}")
    print(f"cost_data_available: {report.cost_data_available} (honest — no LLM call site exists yet)")


def print_reviews(session_factory, settings: Settings) -> None:
    print("\n--- Hourly Review ---")
    hourly = generate_hourly_review(session_factory, settings)
    hourly_id = persist_review(session_factory, hourly)
    print(f"persisted review {hourly_id}")
    print(f"accomplishments: {hourly.accomplishments[:3]}")
    print(f"blockers: {hourly.blockers[:3]}")
    print(f"learning: {hourly.learning[:3]}")

    print("\n--- Weekly Review ---")
    weekly = generate_weekly_review(session_factory, settings)
    weekly_id = persist_review(session_factory, weekly)
    print(f"persisted review {weekly_id}")
    print(f"workflow_evolution: {weekly.workflow_evolution}")
    print(f"model_routing_summary: {weekly.model_routing_summary}")
    print(f"recommendations: {weekly.recommendations}")


def main() -> None:
    settings = Settings.load()
    engine = get_engine(settings.db_path)
    init_db(engine)
    session_factory = make_session_factory(engine)
    event_logger = EventLogger(session_factory, EventBus())

    router = build_router(settings)
    simulate_routing_decisions(session_factory, event_logger, router)
    print_analytics(session_factory)
    print_reviews(session_factory, settings)


if __name__ == "__main__":
    main()
