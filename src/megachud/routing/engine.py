from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ModelProfile:
    name: str
    cost_per_1k_input_tokens: float
    cost_per_1k_output_tokens: float
    quality_tier: int  # higher = better quality
    est_latency_ms: int


@dataclass
class RoutingDecision:
    chosen_model: str
    reason: str
    estimated_cost_usd: float
    candidates_considered: list[str]


class ModelRouter(ABC):
    """Swap point, mirrors reflection.generator.ReflectionGenerator /
    DeterministicReflectionGenerator: a real routing implementation (one
    that actually knows provider pricing/quality/latency, possibly backed
    by live measurements) can replace ConfiguredModelRouter later without
    touching callers.
    """

    @abstractmethod
    def route(
        self,
        task_type: str,
        quality_target: int,
        est_tokens_input: int = 0,
        est_tokens_output: int = 0,
    ) -> RoutingDecision: ...


class NoQualifyingModelError(ValueError):
    pass


def compute_cost_usd(profile: ModelProfile, tokens_input: int, tokens_output: int) -> float:
    """Shared cost arithmetic — used here by ConfiguredModelRouter.route()
    and reused (not duplicated) by every real LLM-call consumer
    (LLMReflectionGenerator, the auto_plan route, CuriosityHandler) once
    they know actual token usage from a real API response."""
    return (
        profile.cost_per_1k_input_tokens / 1000 * tokens_input
        + profile.cost_per_1k_output_tokens / 1000 * tokens_output
    )


class ConfiguredModelRouter(ModelRouter):
    """Pure config lookup + arithmetic — no LLM call anywhere.

    1. Filter profiles to quality_tier >= quality_target; raise
       NoQualifyingModelError if none qualify.
    2. estimated_cost_usd = cost_per_1k_input_tokens/1000 * est_tokens_input
                           + cost_per_1k_output_tokens/1000 * est_tokens_output
       (0 for both token counts if the caller doesn't supply them — cost
       is then 0 for every candidate and est_latency_ms alone decides;
       an honest degenerate case, not a bug.)
    3. Sort qualifying profiles by (estimated_cost_usd, est_latency_ms)
       ascending, pick the first.
    """

    def __init__(self, profiles: list[ModelProfile]) -> None:
        self._profiles = profiles

    def route(
        self,
        task_type: str,
        quality_target: int,
        est_tokens_input: int = 0,
        est_tokens_output: int = 0,
    ) -> RoutingDecision:
        qualifying = [p for p in self._profiles if p.quality_tier >= quality_target]
        if not qualifying:
            raise NoQualifyingModelError(
                f"no configured model profile meets quality_target={quality_target}"
            )

        def estimated_cost(profile: ModelProfile) -> float:
            return compute_cost_usd(profile, est_tokens_input, est_tokens_output)

        ranked = sorted(qualifying, key=lambda p: (estimated_cost(p), p.est_latency_ms))
        winner = ranked[0]
        cost = estimated_cost(winner)

        return RoutingDecision(
            chosen_model=winner.name,
            reason=(
                f"cheapest profile meeting quality_target={quality_target} "
                f"for task_type={task_type!r}: estimated_cost_usd={cost:.6f}, "
                f"est_latency_ms={winner.est_latency_ms}"
            ),
            estimated_cost_usd=cost,
            candidates_considered=[p.name for p in qualifying],
        )
