"""Dev smoke test: run a real 2-step task through the orchestrator end to
end against the dev DB (not pytest's temp DBs), to confirm the full loop
works outside the test harness.
"""

import json

from megachud.config import Settings
from megachud.db import get_engine, init_db, make_session_factory
from megachud.evaluation.engine import EvaluationEngine
from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.task import Task
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.orchestrator.engine import Orchestrator
from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry


def main() -> None:
    settings = Settings.load()
    engine = get_engine(settings.db_path)
    init_db(engine)
    session_factory = make_session_factory(engine)

    event_logger = EventLogger(session_factory, EventBus())

    registry = ToolRegistry()
    registry.register(ReadFileTool(settings.workspace_root))
    registry.register(WriteFileTool(settings.workspace_root))

    approval_gate = ApprovalGate(
        session_factory,
        event_logger,
        timeout_seconds=settings.approval.timeout_seconds,
        poll_interval_seconds=settings.approval.poll_interval_seconds,
    )

    orchestrator = Orchestrator(
        session_factory=session_factory,
        tool_registry=registry,
        approval_gate=approval_gate,
        evaluator=EvaluationEngine(),
        event_logger=event_logger,
        workspace_root=settings.workspace_root,
    )

    def run_plan(title: str, prompt: str, plan: list[dict]) -> None:
        session = session_factory()
        try:
            task = Task(title=title, prompt=prompt, plan_json=json.dumps(plan))
            session.add(task)
            session.commit()
            task_id = task.id
        finally:
            session.close()

        result = orchestrator.run_task(task_id)
        print(f"Task {task_id} ({title!r}) finished with status={result.status.value}")
        print(f"result_summary={result.result_summary}")

    run_plan(
        "dummy smoke task",
        "write then read a file",
        [
            {"tool_name": "write_file", "args": {"path": "dummy_task_output.txt", "content": "hello from run_dummy_task"}},
            {"tool_name": "read_file", "args": {"path": "dummy_task_output.txt"}},
        ],
    )

    run_plan(
        "dummy syntax error task",
        "write a python file with a deliberate syntax error",
        [
            {"tool_name": "write_file", "args": {"path": "broken_output.py", "content": "def f(:\n    pass\n"}},
        ],
    )


if __name__ == "__main__":
    main()
