from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from megachud.api.schemas import TaskCreateRequest, TaskCreateResponse, TaskDetail, TaskSummary, WorkingSummary
from megachud.llm.client import LLMRequestError
from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.task import Task
from megachud.orchestrator.llm_planner import PlanValidationError
from megachud.routing.engine import compute_cost_usd
from megachud.runtime.activity import submit_tracked

router = APIRouter()


@router.post("/tasks", response_model=TaskCreateResponse)
def create_task(payload: TaskCreateRequest, request: Request) -> TaskCreateResponse:
    session_factory = request.app.state.session_factory

    plan_tokens: tuple[str, int, int] | None = None  # (model, tokens_input, tokens_output), if auto-planned

    if payload.auto_plan:
        if payload.tool_calls:
            raise HTTPException(status_code=422, detail="cannot supply both tool_calls and auto_plan")

        planner = request.app.state.llm_task_planner
        if planner is None:
            raise HTTPException(status_code=503, detail="LLM planning is not configured (no ANTHROPIC_API_KEY)")

        try:
            plan_result = planner.plan(payload.prompt, model=payload.model)
        except PlanValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LLMRequestError as exc:
            raise HTTPException(status_code=502, detail=f"LLM planning request failed: {exc}") from exc

        plan = [{"tool_name": c.tool_name, "args": c.args} for c in plan_result.plan]
        plan_tokens = (plan_result.model, plan_result.tokens_input, plan_result.tokens_output)
        plan_model_reason = plan_result.model_reason
    else:
        plan = [{"tool_name": c.tool_name, "args": c.args} for c in payload.tool_calls]

    session = session_factory()
    try:
        task = Task(
            title=payload.title,
            prompt=payload.prompt,
            plan_json=json.dumps(plan),
            execution_mode=payload.execution_mode,
            agent_id=request.app.state.current_agent_id,
            project_name=request.app.state.settings.project_name,
        )
        session.add(task)
        session.commit()
        task_id = task.id
        status = task.status.value
    finally:
        session.close()

    if plan_tokens is not None:
        # Logged here, not inside LLMTaskPlanner.plan(), since no Task row
        # (and therefore no task_id) exists until this point.
        model, tokens_input, tokens_output = plan_tokens
        profiles = request.app.state.model_profiles
        profile = next((p for p in profiles if p.name == model), None)
        cost_usd = compute_cost_usd(profile, tokens_input, tokens_output) if profile is not None else None
        request.app.state.event_logger.log(
            event_type="llm_call",
            task_id=task_id,
            tool_name="llm:planner",
            cost_usd=cost_usd,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            payload={"model": model, "consumer": "planner"},
        )
        tool_names = ", ".join(c["tool_name"] for c in plan) or "(no steps)"
        request.app.state.thought_log.record(
            "planner",
            f"Planned {len(plan)} step(s) for '{payload.title}' [{model} — {plan_model_reason}]: {tool_names}",
        )

    orchestrator = request.app.state.orchestrator
    submit_tracked(request.app.state.executor, request.app.state.activity, orchestrator.run_task, task_id)

    return TaskCreateResponse(id=task_id, status=status)


@router.get("/tasks", response_model=list[TaskSummary])
def list_tasks(request: Request, agent_id: str | None = None) -> list[TaskSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        query = session.query(Task)
        if agent_id:
            query = query.filter_by(agent_id=agent_id)
        tasks = query.order_by(Task.created_at.desc()).all()
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
