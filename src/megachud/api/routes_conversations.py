from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from megachud.api.schemas import (
    ConversationMessageCreateRequest,
    ConversationMessageCreateResponse,
    ConversationMessageSummary,
    ConversationSummary,
    PlanDecisionResponse,
)
from megachud.llm.client import LLMRequestError
from megachud.models.conversation import Conversation, ConversationMessage
from megachud.models.task import Task
from megachud.orchestrator.plan_validation import PlanValidationError
from megachud.orchestrator.task_models import ToolCall
from megachud.routing.engine import compute_cost_usd

router = APIRouter()


def _message_summary(m: ConversationMessage) -> ConversationMessageSummary:
    return ConversationMessageSummary(
        id=m.id,
        role=m.role,
        content=m.content,
        created_at=m.created_at.isoformat(),
        linked_task_id=m.linked_task_id,
        proposed_plan=json.loads(m.proposed_plan_json) if m.proposed_plan_json else None,
        plan_status=m.plan_status,
        execution_mode=m.execution_mode,
    )


def _launch_task_from_plan(request: Request, *, title: str, prompt: str, plan, execution_mode: str) -> str:
    """Create a Task from a validated plan and submit it to the same
    executor/orchestrator plain POST /tasks uses — the exact call shape,
    just reached from the chat flow instead. `plan` is a list[ToolCall]."""
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        task = Task(
            title=title[:200],
            prompt=prompt,
            plan_json=json.dumps([{"tool_name": c.tool_name, "args": c.args} for c in plan]),
            execution_mode=execution_mode,
            agent_id=request.app.state.current_agent_id,
            project_name=request.app.state.settings.project_name,
        )
        session.add(task)
        session.commit()
        task_id = task.id
    finally:
        session.close()
    request.app.state.executor.submit(request.app.state.orchestrator.run_task, task_id)
    return task_id


def _log_conversation_llm_cost(request: Request, *, task_id, model, tokens_input, tokens_output, message_id, conversation_id) -> None:
    profiles = request.app.state.model_profiles
    profile = next((p for p in profiles if p.name == model), None)
    cost_usd = compute_cost_usd(profile, tokens_input, tokens_output) if profile is not None else None
    request.app.state.event_logger.log(
        event_type="llm_call",
        task_id=task_id,
        tool_name="llm:conversation",
        cost_usd=cost_usd,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        payload={"model": model, "consumer": "conversation", "conversation_id": conversation_id, "message_id": message_id},
    )


@router.post("/conversations", response_model=ConversationSummary)
def create_conversation(request: Request) -> ConversationSummary:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        conversation = Conversation(
            agent_id=request.app.state.current_agent_id,
            project_name=request.app.state.settings.project_name,
        )
        session.add(conversation)
        session.commit()
        return ConversationSummary(
            id=conversation.id, created_at=conversation.created_at.isoformat(), message_count=0, last_message_preview=None
        )
    finally:
        session.close()


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(request: Request, agent_id: str | None = None) -> list[ConversationSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        query = session.query(Conversation)
        if agent_id:
            query = query.filter_by(agent_id=agent_id)
        conversations = query.order_by(Conversation.created_at.desc()).all()

        summaries = []
        for c in conversations:
            messages = (
                session.query(ConversationMessage)
                .filter_by(conversation_id=c.id)
                .order_by(ConversationMessage.created_at.asc())
                .all()
            )
            preview = messages[0].content[:100] if messages else None
            summaries.append(
                ConversationSummary(
                    id=c.id, created_at=c.created_at.isoformat(), message_count=len(messages), last_message_preview=preview
                )
            )
        return summaries
    finally:
        session.close()


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageSummary])
def list_messages(conversation_id: str, request: Request) -> list[ConversationMessageSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        messages = (
            session.query(ConversationMessage)
            .filter_by(conversation_id=conversation_id)
            .order_by(ConversationMessage.created_at.asc())
            .all()
        )
        return [_message_summary(m) for m in messages]
    finally:
        session.close()


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessageCreateResponse)
def send_message(
    conversation_id: str, payload: ConversationMessageCreateRequest, request: Request
) -> ConversationMessageCreateResponse:
    session_factory = request.app.state.session_factory

    session = session_factory()
    try:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")

        engine = request.app.state.conversation_engine
        if engine is None:
            raise HTTPException(status_code=503, detail="Conversation is not configured (no ANTHROPIC_API_KEY)")

        pending = (
            session.query(ConversationMessage)
            .filter_by(conversation_id=conversation_id, plan_status="pending")
            .first()
        )
        if pending is not None:
            raise HTTPException(status_code=409, detail="a proposed plan is still pending approval/rejection")

        prior_messages = (
            session.query(ConversationMessage)
            .filter_by(conversation_id=conversation_id)
            .order_by(ConversationMessage.created_at.asc())
            .all()
        )
        history = [{"role": m.role, "content": m.content} for m in prior_messages]

        user_message = ConversationMessage(conversation_id=conversation_id, role="user", content=payload.content)
        session.add(user_message)
        session.commit()
        session.refresh(user_message)
        user_summary = _message_summary(user_message)
    finally:
        session.close()

    # From here on, exactly one assistant message must ALWAYS be written,
    # even on failure — Anthropic's Messages API requires strict
    # user/assistant alternation, so a dangling unanswered user turn would
    # break the next call's history.
    try:
        turn = engine.respond(history, payload.content)
    except (LLMRequestError, PlanValidationError) as exc:
        assistant_message = _persist_assistant_message(
            session_factory, conversation_id, content=f"I couldn't respond right now: {exc}"
        )
        return ConversationMessageCreateResponse(user_message=user_summary, assistant_message=assistant_message)

    if turn.action == "ask_question":
        assistant_message = _persist_assistant_message(session_factory, conversation_id, content=turn.message)
        _log_conversation_llm_cost(
            request, task_id=None, model=turn.model, tokens_input=turn.tokens_input, tokens_output=turn.tokens_output,
            message_id=assistant_message.id, conversation_id=conversation_id,
        )
        return ConversationMessageCreateResponse(user_message=user_summary, assistant_message=assistant_message)

    # action == "propose_plan"
    plan_json = json.dumps([{"tool_name": c.tool_name, "args": c.args} for c in turn.plan])

    if payload.execution_mode == "semi_manual":
        assistant_message = _persist_assistant_message(
            session_factory, conversation_id, content=turn.message,
            proposed_plan_json=plan_json, plan_status="pending", execution_mode=payload.execution_mode,
        )
        _log_conversation_llm_cost(
            request, task_id=None, model=turn.model, tokens_input=turn.tokens_input, tokens_output=turn.tokens_output,
            message_id=assistant_message.id, conversation_id=conversation_id,
        )
        return ConversationMessageCreateResponse(user_message=user_summary, assistant_message=assistant_message)

    # "auto" / "full_manual" -> launch immediately, no separate approval step
    task_id = _launch_task_from_plan(
        request, title=payload.content, prompt=payload.content, plan=turn.plan, execution_mode=payload.execution_mode
    )
    assistant_message = _persist_assistant_message(
        session_factory, conversation_id, content=turn.message,
        proposed_plan_json=plan_json, plan_status=None, execution_mode=payload.execution_mode, linked_task_id=task_id,
    )
    _log_conversation_llm_cost(
        request, task_id=task_id, model=turn.model, tokens_input=turn.tokens_input, tokens_output=turn.tokens_output,
        message_id=assistant_message.id, conversation_id=conversation_id,
    )
    return ConversationMessageCreateResponse(user_message=user_summary, assistant_message=assistant_message)


def _persist_assistant_message(
    session_factory, conversation_id: str, *, content: str, proposed_plan_json=None, plan_status=None,
    execution_mode=None, linked_task_id=None,
) -> ConversationMessageSummary:
    session = session_factory()
    try:
        message = ConversationMessage(
            conversation_id=conversation_id, role="assistant", content=content,
            proposed_plan_json=proposed_plan_json, plan_status=plan_status,
            execution_mode=execution_mode, linked_task_id=linked_task_id,
        )
        session.add(message)
        session.commit()
        session.refresh(message)
        return _message_summary(message)
    finally:
        session.close()


@router.post("/conversations/{conversation_id}/messages/{message_id}/approve_plan", response_model=PlanDecisionResponse)
def approve_plan(conversation_id: str, message_id: str, request: Request) -> PlanDecisionResponse:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        message = session.get(ConversationMessage, message_id)
        if message is None or message.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="message not found")
        if message.plan_status != "pending":
            raise HTTPException(status_code=409, detail=f"plan is not pending (status={message.plan_status})")

        plan_steps = json.loads(message.proposed_plan_json)
        # The user message that triggered this proposal — needed as the
        # Task's `prompt`. Strict user/assistant alternation (enforced by
        # send_message always writing exactly one of each) guarantees the
        # most recent prior user message is the right one.
        preceding_user = (
            session.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.role == "user",
                ConversationMessage.created_at < message.created_at,
            )
            .order_by(ConversationMessage.created_at.desc())
            .first()
        )
        prompt = preceding_user.content if preceding_user is not None else message.content
    finally:
        session.close()

    plan = [ToolCall(tool_name=s["tool_name"], args=s["args"]) for s in plan_steps]
    task_id = _launch_task_from_plan(request, title=prompt, prompt=prompt, plan=plan, execution_mode="semi_manual")

    session = session_factory()
    try:
        message = session.get(ConversationMessage, message_id)
        message.plan_status = "approved"
        message.linked_task_id = task_id
        session.commit()
        session.refresh(message)
        return PlanDecisionResponse(message=_message_summary(message), task_id=task_id)
    finally:
        session.close()


@router.post("/conversations/{conversation_id}/messages/{message_id}/reject_plan", response_model=PlanDecisionResponse)
def reject_plan(conversation_id: str, message_id: str, request: Request) -> PlanDecisionResponse:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        message = session.get(ConversationMessage, message_id)
        if message is None or message.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="message not found")
        if message.plan_status != "pending":
            raise HTTPException(status_code=409, detail=f"plan is not pending (status={message.plan_status})")

        message.plan_status = "rejected"
        session.commit()
        session.refresh(message)
        return PlanDecisionResponse(message=_message_summary(message), task_id=None)
    finally:
        session.close()
