"""Stage B browser-automation demo: runs a real task that opens a page in
a real Chromium via browser_navigate and extracts it with browser_read,
through the real orchestrator (create_app wiring), then prints the result.

Requires a one-time `playwright install chromium`. If Playwright or its
browser binary is missing, the browser tools fail gracefully and this
script prints a clear message and exits cleanly — same graceful-
degradation pattern as run_llm_demo.py / run_internet_demo.py.

Interaction (browser_fill / browser_click) and the approval-gated
browser_submit exist too; this demo stays read-only (navigate + read) so
it needs no human at the keyboard to approve anything.
"""

from __future__ import annotations

import json
import sys

from megachud.api.app import create_app
from megachud.config import Settings
from megachud.models.event import Event
from megachud.models.task import Task

DEMO_URL = "https://example.com/"


def main() -> None:
    # Page content is arbitrary internet text — avoid a cp1252 crash on
    # Windows consoles (see run_internet_demo.py).
    sys.stdout.reconfigure(errors="replace")

    settings = Settings.load()
    app = create_app(settings)
    session_factory = app.state.session_factory
    orchestrator = app.state.orchestrator
    manager = app.state.browser_manager

    plan = [
        {"tool_name": "browser_navigate", "args": {"url": DEMO_URL}},
        {"tool_name": "browser_read", "args": {"mode": "text"}},
    ]
    session = session_factory()
    try:
        task = Task(
            title="browser demo: navigate + read",
            prompt=f"open {DEMO_URL} in a real browser and read it",
            plan_json=json.dumps(plan),
            agent_id=app.state.current_agent_id,
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
        events = (
            session.query(Event)
            .filter_by(task_id=task_id, event_type="tool_result")
            .order_by(Event.id)
            .all()
        )
        print("\n--- tool_result events ---")
        for event in events:
            payload = json.loads(event.payload_json)
            preview = payload["output"][:120].replace("\n", " ")
            print(f"  {event.tool_name}: success={payload['success']} output={preview!r}")
    finally:
        session.close()

    print(f"\nBrowser session cleaned up after the task: {not manager.has_session(task_id)}")
    if finished.status.value != "succeeded":
        print(
            "\nIf the browser tools failed, install the browser binary once with:\n"
            "  .venv/Scripts/python -m playwright install chromium"
        )
    manager.close_all()


if __name__ == "__main__":
    main()
