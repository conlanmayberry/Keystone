from __future__ import annotations

from fastapi import APIRouter, Request

from megachud.api.schemas import AgentSummary
from megachud.models.agent import Agent

router = APIRouter()


@router.get("/agents", response_model=list[AgentSummary])
def list_agents(request: Request) -> list[AgentSummary]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        agents = session.query(Agent).order_by(Agent.name).all()
        return [
            AgentSummary(id=a.id, name=a.name, description=a.description, created_at=a.created_at.isoformat())
            for a in agents
        ]
    finally:
        session.close()
