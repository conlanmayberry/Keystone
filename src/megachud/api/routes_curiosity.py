from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from megachud.api.schemas import (
    PendingQuestionSummary,
    QuestionAnswerRequest,
    ResearchObjectiveSummary,
)
from megachud.curiosity.answers import answer_question
from megachud.models.curiosity import PendingQuestion, QuestionStatus, ResearchObjective

router = APIRouter()


def _question_summary(question: PendingQuestion) -> PendingQuestionSummary:
    return PendingQuestionSummary(
        id=question.id,
        source_task_id=question.source_task_id,
        question=question.question,
        context=question.context,
        status=question.status.value,
        answer=question.answer,
        created_at=question.created_at.isoformat(),
    )


def _objective_summary(objective: ResearchObjective) -> ResearchObjectiveSummary:
    return ResearchObjectiveSummary(
        id=objective.id,
        source_task_id=objective.source_task_id,
        objective_type=objective.objective_type,
        description=objective.description,
        findings=json.loads(objective.findings_json),
        resolved=objective.resolved,
        created_at=objective.created_at.isoformat(),
    )


@router.get("/questions", response_model=list[PendingQuestionSummary])
def list_questions(request: Request, status: str = "pending") -> list[PendingQuestionSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        query = session.query(PendingQuestion)
        if status:
            query = query.filter_by(status=QuestionStatus(status))
        questions = query.order_by(PendingQuestion.created_at.desc()).all()
        return [_question_summary(q) for q in questions]
    finally:
        session.close()


@router.post("/questions/{question_id}/answer", response_model=PendingQuestionSummary)
def answer(question_id: str, payload: QuestionAnswerRequest, request: Request) -> PendingQuestionSummary:
    session_factory = request.app.state.session_factory
    memory_store = request.app.state.memory_store
    vault_writer = request.app.state.vault_writer
    try:
        answer_question(session_factory, memory_store, vault_writer, question_id, payload.answer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="question not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session = session_factory()
    try:
        question = session.get(PendingQuestion, question_id)
        return _question_summary(question)
    finally:
        session.close()


@router.get("/research_objectives", response_model=list[ResearchObjectiveSummary])
def list_research_objectives(request: Request, resolved: bool | None = None) -> list[ResearchObjectiveSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        query = session.query(ResearchObjective)
        if resolved is not None:
            query = query.filter_by(resolved=resolved)
        objectives = query.order_by(ResearchObjective.created_at.desc()).limit(50).all()
        return [_objective_summary(o) for o in objectives]
    finally:
        session.close()
