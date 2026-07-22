from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from megachud.api.schemas import PromptDraftRequest, PromptDraftResponse
from megachud.conversation.prompt_drafter import PromptDraftResult
from megachud.llm.client import LLMRequestError
from megachud.routing.engine import compute_cost_usd

router = APIRouter()


def _log_prompt_drafter_llm_cost(request: Request, result: PromptDraftResult) -> None:
    profiles = request.app.state.model_profiles
    profile = next((p for p in profiles if p.name == result.model), None)
    cost_usd = compute_cost_usd(profile, result.tokens_input, result.tokens_output) if profile is not None else None
    request.app.state.event_logger.log(
        event_type="llm_call",
        task_id=None,
        tool_name="llm:prompt_drafter",
        cost_usd=cost_usd,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        payload={"model": result.model, "consumer": "prompt_drafter"},
    )


@router.post("/prompts/draft", response_model=PromptDraftResponse)
def draft_prompt(payload: PromptDraftRequest, request: Request) -> PromptDraftResponse:
    drafter = request.app.state.prompt_drafter
    if drafter is None:
        raise HTTPException(status_code=503, detail="Prompt drafting is not configured (no ANTHROPIC_API_KEY)")

    try:
        result = drafter.draft(payload.raw_text)
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _log_prompt_drafter_llm_cost(request, result)
    return PromptDraftResponse(prompt=result.prompt, model=result.model)
