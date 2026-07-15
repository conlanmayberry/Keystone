"""Proves Phase 2's acceptance criterion — "agent improves recall across
sessions" — by running this script as TWO SEPARATE process invocations
against the real dev DB/vault:

  python scripts/run_memory_demo.py record
    Creates and runs a real task through the orchestrator, letting the
    reflection -> memory -> vault pipeline fire.

  python scripts/run_memory_demo.py recall
    (In a FRESH `python` process.) Queries memory for text similar to the
    recorded task's prompt and prints ranked results, proving retrieval
    works from a cold process against only what's persisted on disk.
"""

import json
import sys

from megachud.config import Settings
from megachud.db import get_engine, init_db, make_session_factory
from megachud.evaluation.engine import EvaluationEngine
from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.memory.retrieval import search
from megachud.memory.store import MemoryStore
from megachud.models.task import Task
from megachud.obsidian.vault import VaultWriter
from megachud.orchestrator.approval_gate import ApprovalGate
from megachud.orchestrator.engine import Orchestrator
from megachud.reflection.engine import ReflectionEngine
from megachud.reflection.handler import TaskCompletionHandler
from megachud.tools.file_tools import ReadFileTool, WriteFileTool
from megachud.tools.registry import ToolRegistry

DEMO_PROMPT = "organize a birthday party checklist in a text file"


def _build(settings: Settings):
    engine = get_engine(settings.db_path)
    init_db(engine)
    session_factory = make_session_factory(engine)

    reflection_engine = ReflectionEngine(session_factory)
    memory_store = MemoryStore(session_factory, vector_dim=settings.memory.vector_dim)
    vault_writer = VaultWriter(settings.vault_root)
    handler = TaskCompletionHandler(reflection_engine, memory_store, vault_writer)
    event_logger = EventLogger(session_factory, EventBus(), on_event=handler)

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
    return session_factory, orchestrator


def record() -> None:
    settings = Settings.load()
    session_factory, orchestrator = _build(settings)

    plan = [
        {
            "tool_name": "write_file",
            "args": {"path": "birthday_checklist.txt", "content": "balloons\ncake\ninvitations"},
        }
    ]

    session = session_factory()
    try:
        task = Task(title="Birthday party checklist", prompt=DEMO_PROMPT, plan_json=json.dumps(plan))
        session.add(task)
        session.commit()
        task_id = task.id
    finally:
        session.close()

    result = orchestrator.run_task(task_id)
    print(f"Recorded task {task_id} with status={result.status.value}")
    print()
    print("Now run this in a NEW process to prove retrieval survives a cold start:")
    print("  python scripts/run_memory_demo.py recall")


def recall(query_text: str | None) -> None:
    settings = Settings.load()
    session_factory, _ = _build(settings)

    query = query_text or "planning a checklist for a birthday celebration"
    print(f"Querying memory (fresh process, no state from 'record') for: {query!r}")
    print()

    results = search(session_factory, query, settings.memory.vector_dim, top_k=5)
    if not results:
        print("No memory entries found. Run 'record' first (in a separate invocation).")
        return

    for scored in results:
        entry = scored.entry
        print(f"[{scored.score:.3f}] ({entry.memory_type.value}) {entry.title}")
        print(f"    {entry.content[:150]!r}")
        print(f"    vault: {entry.vault_path}")
        print()


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("record", "recall"):
        print("usage: python scripts/run_memory_demo.py [record|recall] [optional recall query]")
        raise SystemExit(1)

    if sys.argv[1] == "record":
        record()
    else:
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else None
        recall(query)


if __name__ == "__main__":
    main()
