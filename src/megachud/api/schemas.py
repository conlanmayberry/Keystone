from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ToolCallIn(BaseModel):
    tool_name: str
    args: dict[str, Any] = {}


class TaskCreateRequest(BaseModel):
    title: str
    prompt: str
    tool_calls: list[ToolCallIn] = []


class TaskCreateResponse(BaseModel):
    id: str
    status: str


class TaskSummary(BaseModel):
    id: str
    title: str
    status: str
    created_at: str
    completed_at: str | None = None


class TaskDetail(BaseModel):
    id: str
    title: str
    prompt: str
    status: str
    created_at: str
    started_at: str | None
    completed_at: str | None
    result_summary: str | None
    events: list[dict[str, Any]]
    evaluation: dict[str, Any] | None


class ApprovalDecisionRequest(BaseModel):
    approved: bool
    note: str | None = None


class ApprovalSummary(BaseModel):
    id: str
    task_id: str
    tool_name: str
    risk_level: str
    status: str
    created_at: str
    request_payload: dict[str, Any]


class WorkingSummary(BaseModel):
    """Spec's exact fields — deliberately NOT chain-of-thought. Phase 1
    derives this deterministically from Task state (no LLM planner yet);
    the JSON shape stays stable for when a later phase adds a real
    LLM-driven summarizer.
    """

    objective: str
    plan: list[str]
    assumptions: list[str]
    blockers: list[str]
    next_step: str | None
    rationale: str


class MemoryEntrySummary(BaseModel):
    id: str
    memory_type: str
    title: str
    content: str
    tags: list[str]
    created_at: str
    source_task_id: str | None
    vault_path: str | None


class MemorySearchResult(BaseModel):
    entry: MemoryEntrySummary
    score: float


class MemoryCreateRequest(BaseModel):
    title: str
    content: str
    tags: list[str] = []
