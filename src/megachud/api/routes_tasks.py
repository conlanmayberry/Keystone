from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from megachud.api.schemas import TaskCreateRequest, TaskCreateResponse, TaskDetail, TaskSummary, WorkingSummary
from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.task import Task

router = APIRouter()


@router.post("/tasks", response_model=TaskCreateResponse)
def create_task(payload: TaskCreateRequest, request: Request) -> TaskCreateResponse:
    session_factory = request.app.state.session_factory
    plan = [{"tool_name": c.tool_name, "args": c.args} for c in payload.tool_calls]

    session = session_factory()
    try:
        task = Task(title=payload.title, prompt=payload.prompt, plan_json=json.dumps(plan))
        session.add(task)
        session.commit()
        task_id = task.id
        status = task.status.value
    finally:
        session.close()

    orchestrator = request.app.state.orchestrator
    request.app.state.executor.submit(orchestrator.run_task, task_id)

    return TaskCreateResponse(id=task_id, status=status)


@router.get("/tasks", response_model=list[TaskSummary])
def list_tasks(request: Request) -> list[TaskSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        tasks = session.query(Task).order_by(Task.created_at.desc()).all()
        return [
            TaskSummary(
                id=t.id,
                title=t.title,
                status=t.status.value,
                created_at=t.created_at.isoformat(),
                completed_at=t.completed_at.isoformat() if t.completed_at else None,
            )
            for t in tasks
        ]
    finally:
        session.close()


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: str, request: Request) -> TaskDetail:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")

        events = session.query(Event).filter_by(task_id=task_id).order_by(Event.id).all()
        evaluation = (
            session.query(Evaluation).filter_by(task_id=task_id).order_by(Evaluation.id.desc()).first()
        )

        return TaskDetail(
            id=task.id,
            title=task.title,
            prompt=task.prompt,
            status=task.status.value,
            created_at=task.created_at.isoformat(),
            started_at=task.started_at.isoformat() if task.started_at else None,
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
            result_summary=task.result_summary,
            events=[
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "tool_name": e.tool_name,
                    "duration_ms": e.duration_ms,
                    "timestamp": e.created_at.isoformat(),
                    "payload": json.loads(e.payload_json),
                }
                for e in events
            ],
            evaluation=(
                {"success": evaluation.success, "checks": json.loads(evaluation.checks_json)}
                if evaluation is not None
                else None
            ),
        )
    finally:
        session.close()


@router.get("/tasks/{task_id}/working_summary", response_model=WorkingSummary)
def get_working_summary(task_id: str, request: Request) -> WorkingSummary:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")

        plan = json.loads(task.plan_json)
        plan_lines = [f"{i + 1}. {c['tool_name']}({c.get('args', {})})" for i, c in enumerate(plan)]

        blockers: list[str] = []
        if task.status.value == "awaiting_approval":
            blockers.append("awaiting human approval")

        in_flight = task.status.value in ("pending", "running", "awaiting_approval")

        return WorkingSummary(
            objective=task.prompt,
            plan=plan_lines,
            assumptions=[],
            blockers=blockers,
            next_step="continue executing plan" if in_flight else None,
            rationale=task.result_summary or "in progress",
        )
    finally:
        session.close()
