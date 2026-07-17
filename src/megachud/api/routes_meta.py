from __future__ import annotations

from fastapi import APIRouter, Request

from megachud.api.schemas import MetaSummary

router = APIRouter()


@router.get("/meta", response_model=MetaSummary)
def get_meta(request: Request) -> MetaSummary:
    settings = request.app.state.settings
    return MetaSummary(project_name=settings.project_name, agent_name=settings.agent_name)
