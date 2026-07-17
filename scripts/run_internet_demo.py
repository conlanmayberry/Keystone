"""First real internet-access demo: http_fetch and download_file (always
available, no API key required) plus web_search (Brave Search API, only
if BRAVE_API_KEY is configured) — all built the exact way app.py wires
them, via create_app(), so this exercises the real production wiring
rather than a parallel hand-built stack.

Run this against the real dev DB. http_fetch/download_file work
immediately with no setup; web_search prints a clear "not configured"
message and is skipped gracefully if no key is present, same pattern as
scripts/run_llm_demo.py's no-key path.
"""

from __future__ import annotations

import json

from megachud.api.app import create_app
from megachud.config import Settings
from megachud.models.event import Event
from megachud.models.task import Task

DEMO_URL = "https://example.com/"


def run_fetch_and_download(app, settings: Settings) -> None:
    session_factory = app.state.session_factory
    orchestrator = app.state.orchestrator
    agent_id = app.state.current_agent_id

    plan = [
        {"tool_name": "http_fetch", "args": {"url": DEMO_URL}},
        {"tool_name": "download_file", "args": {"url": DEMO_URL, "filename": "example.html"}},
    ]
    session = session_factory()
    try:
        task = Task(
            title="internet demo: fetch + download",
            prompt=f"fetch and download {DEMO_URL}",
            plan_json=json.dumps(plan),
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
        events = (
            session.query(Event)
            .filter_by(task_id=task_id, event_type="tool_result")
            .order_by(Event.id)
            .all()
        )
        print("\n--- tool_result events ---")
        for event in events:
            payload = json.loads(event.payload_json)
            output_preview = payload["output"][:150].replace("\n", " ")
            print(f"  {event.tool_name}: success={payload['success']} output={output_preview!r}")
    finally:
        session.close()


def run_search(app, settings: Settings) -> None:
    print("\n--- web_search ---")
    if not settings.brave_api_key:
        print(
            "No BRAVE_API_KEY found (neither in the environment nor in .env) — "
            "web_search was not registered; http_fetch and download_file work "
            "regardless. Add BRAVE_API_KEY to .env to exercise this for real."
        )
        return

    tool = app.state.tool_registry.get("web_search")
    result = tool.run({"query": "MegaChud autonomous agent platform"})
    print(f"success={result.success}")
    if result.success:
        for r in result.metadata["results"][:3]:
            print(f"  - {r['title']} ({r['url']})")
    else:
        print(f"error={result.error}")


def print_downloads_usage(settings: Settings) -> None:
    downloads_dir = settings.workspace_root / "downloads"
    total = sum(f.stat().st_size for f in downloads_dir.iterdir() if f.is_file()) if downloads_dir.is_dir() else 0
    print(f"\n--- workspace/downloads/ usage ---\n{total} / {settings.internet.download.max_folder_bytes} bytes")


def main() -> None:
    settings = Settings.load()
    app = create_app(settings)

    run_fetch_and_download(app, settings)
    run_search(app, settings)
    print_downloads_usage(settings)


if __name__ == "__main__":
    main()
