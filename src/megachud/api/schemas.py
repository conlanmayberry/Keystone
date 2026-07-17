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


class StrategySummary(BaseModel):
    id: str
    workflow_name: str
    version: int
    is_active: bool
    title: str
    description: str
    plan_template: list[dict[str, Any]]
    parameters: list[str]
    tags: list[str]
    origin: str
    sample_count: int
    success_count: int
    success_rate: float
    mean_duration_ms: float
    mean_score: float | None
    created_at: str


class StrategyCreateRequest(BaseModel):
    workflow_name: str
    title: str
    description: str = ""
    plan_template: list[dict[str, Any]]
    parameters: list[str] = []
    tags: list[str] = []


class StrategyUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    plan_template: list[dict[str, Any]] | None = None
    parameters: list[str] | None = None
    tags: list[str] | None = None


class StrategyInvokeRequest(BaseModel):
    params: dict[str, Any] = {}
    title: str | None = None


class StrategyInvokeResponse(BaseModel):
    task_id: str


class ExperimentSummary(BaseModel):
    id: str
    workflow_name: str
    hypothesis: str
    control_strategy_id: str
    variant_strategy_id: str
    minimum_sample_size: int
    status: str
    recommendation: str | None
    result: dict[str, Any] | None
    created_at: str


class ExperimentCreateRequest(BaseModel):
    workflow_name: str
    hypothesis: str
    control_strategy_id: str
    variant_strategy_id: str
    minimum_sample_size: int = 10


class PromotionSummary(BaseModel):
    id: str
    experiment_id: str
    workflow_name: str
    from_strategy_id: str
    to_strategy_id: str
    justification: str
    status: str
    created_at: str


class PromotionDecisionRequest(BaseModel):
    approved: bool
    note: str | None = None


class PendingQuestionSummary(BaseModel):
    id: str
    source_task_id: str | None
    question: str
    context: str
    status: str
    answer: str | None
    created_at: str


class QuestionAnswerRequest(BaseModel):
    answer: str


class ResearchObjectiveSummary(BaseModel):
    id: str
    source_task_id: str | None
    objective_type: str
    description: str
    findings: list[dict[str, Any]]
    resolved: bool
    created_at: str


class BottleneckFindingSummary(BaseModel):
    kind: str
    subject: str
    detail: str
    severity: float


class ProposeExperimentRequest(BaseModel):
    """Mirrors bottleneck.finder.BottleneckFinding — the frontend already
    has these fields from its last GET /bottlenecks call, so the route
    reconstructs the finding from the request body instead of re-running
    the (heavier) scan just to look one finding back up.
    """

    kind: str
    subject: str
    detail: str
    severity: float


class AnalyticsReportSummary(BaseModel):
    window_start: str
    window_end: str
    task_counts_by_status: dict[str, int]
    tool_call_counts: dict[str, int]
    tool_failure_rates: dict[str, float]
    event_counts_by_type: dict[str, int]
    strategy_success_rates: dict[str, float]
    experiment_outcome_counts: dict[str, int]
    become_long_term_knowledge_rate: float
    total_cost_usd: float
    total_tokens_input: int
    total_tokens_output: int
    cost_data_available: bool


class ReviewReportSummary(BaseModel):
    kind: str
    window_start: str
    window_end: str
    accomplishments: list[str]
    blockers: list[str]
    learning: list[str]
    costs: dict[str, Any]
    metrics: AnalyticsReportSummary
    workflow_evolution: list[dict[str, Any]] | None = None
    strategy_effectiveness: list[dict[str, Any]] | None = None
    model_routing_summary: dict[str, int] | None = None
    experiments_summary: list[dict[str, Any]] | None = None
    recommendations: list[str] | None = None


class ReviewSummary(BaseModel):
    id: str
    kind: str
    window_start: str
    window_end: str
    created_at: str


class ModelProfileSummary(BaseModel):
    name: str
    cost_per_1k_input_tokens: float
    cost_per_1k_output_tokens: float
    quality_tier: int
    est_latency_ms: int


class RouteSimulateRequest(BaseModel):
    task_type: str
    quality_target: int
    est_tokens_input: int = 0
    est_tokens_output: int = 0


class RoutingDecisionSummary(BaseModel):
    chosen_model: str
    reason: str
    estimated_cost_usd: float
    candidates_considered: list[str]


class AgentSummary(BaseModel):
    id: str
    name: str
    description: str
    created_at: str


class MetaSummary(BaseModel):
    project_name: str
    agent_name: str


class PluginLoadResultSummary(BaseModel):
    name: str
    source: str
    success: bool
    error: str | None = None
