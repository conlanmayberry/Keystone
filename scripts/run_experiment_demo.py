"""Phase 3 end-to-end demo, built incrementally across all 6 build steps.

Step 1 (this version): seed one Strategy, invoke it, print the rendered
plan. The task is created but not yet run — orchestrator wiring and the
strategy_invoked event linkage arrive in Step 2.
"""

import json

from megachud.config import Settings
from megachud.db import get_engine, init_db, make_session_factory
from megachud.models.strategy import Strategy
from megachud.strategy.invoker import invoke_strategy

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


def main() -> None:
    settings = Settings.load()
    engine = get_engine(settings.db_path)
    init_db(engine)
    session_factory = make_session_factory(engine)

    strategy_id = seed_strategy(session_factory)
    print(f"Strategy: {strategy_id}")

    task_id = invoke_strategy(session_factory, strategy_id, {"filename": "greeting.txt", "name": "MegaChud"})
    print(f"Invoked -> task {task_id} (not yet run)")

    from megachud.models.task import Task

    session = session_factory()
    try:
        task = session.get(Task, task_id)
        print(f"Rendered plan: {task.plan_json}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
