from __future__ import annotations

from fastapi import APIRouter, Request

from megachud.models.task import Task, TaskStatus

router = APIRouter()


@router.get("/status")
def get_status(request: Request) -> dict:
    """Live "is the agent working, and for how long" view. Combines the
    in-memory ActivityTracker (in-flight work, uptime, current-burst
    duration) with an authoritative DB count of tasks the orchestrator
    still has open (running / awaiting_approval) — the latter survives
    even if in-memory counters and the DB ever disagree after a restart.
    """
    snapshot = request.app.state.activity.snapshot()

    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        open_tasks = (
            session.query(Task)
            .filter(Task.status.in_([TaskStatus.RUNNING, TaskStatus.AWAITING_APPROVAL]))
            .count()
        )
    finally:
        session.close()

    snapshot["open_tasks"] = open_tasks
    return snapshot


@router.get("/thoughts")
def get_thoughts(request: Request) -> list[dict]:
    return request.app.state.thought_log.recent()
