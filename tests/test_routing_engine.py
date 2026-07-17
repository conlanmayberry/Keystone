from __future__ import annotations

import pytest

from megachud.routing.engine import ConfiguredModelRouter, ModelProfile, NoQualifyingModelError

FAST_CHEAP = ModelProfile("fast-cheap", cost_per_1k_input_tokens=0.0002, cost_per_1k_output_tokens=0.0006, quality_tier=1, est_latency_ms=400)
BALANCED = ModelProfile("balanced", cost_per_1k_input_tokens=0.001, cost_per_1k_output_tokens=0.003, quality_tier=2, est_latency_ms=900)
PREMIUM = ModelProfile("premium", cost_per_1k_input_tokens=0.005, cost_per_1k_output_tokens=0.015, quality_tier=3, est_latency_ms=1800)


def test_picks_cheapest_profile_meeting_quality_target():
    router = ConfiguredModelRouter([FAST_CHEAP, BALANCED, PREMIUM])
    decision = router.route("summarize", quality_target=2, est_tokens_input=1000, est_tokens_output=500)
    assert decision.chosen_model == "balanced"
    assert set(decision.candidates_considered) == {"balanced", "premium"}


def test_quality_target_1_picks_fast_cheap():
    router = ConfiguredModelRouter([FAST_CHEAP, BALANCED, PREMIUM])
    decision = router.route("classify", quality_target=1, est_tokens_input=100, est_tokens_output=10)
    assert decision.chosen_model == "fast-cheap"


def test_no_qualifying_profile_raises():
    router = ConfiguredModelRouter([FAST_CHEAP, BALANCED])
    with pytest.raises(NoQualifyingModelError):
        router.route("hard_task", quality_target=5)


def test_zero_estimated_tokens_falls_back_to_latency():
    # With no token estimate, cost is 0 for every candidate, so the
    # cheapest-lowest-latency profile among qualifying ones wins.
    router = ConfiguredModelRouter([BALANCED, PREMIUM])
    decision = router.route("unknown", quality_target=2)
    assert decision.chosen_model == "balanced"
    assert decision.estimated_cost_usd == 0.0


def test_tie_break_by_latency_when_cost_equal():
    cheap_slow = ModelProfile("cheap-slow", cost_per_1k_input_tokens=0.001, cost_per_1k_output_tokens=0.001, quality_tier=2, est_latency_ms=2000)
    cheap_fast = ModelProfile("cheap-fast", cost_per_1k_input_tokens=0.001, cost_per_1k_output_tokens=0.001, quality_tier=2, est_latency_ms=100)
    router = ConfiguredModelRouter([cheap_slow, cheap_fast])
    decision = router.route("task", quality_target=2, est_tokens_input=100, est_tokens_output=100)
    assert decision.chosen_model == "cheap-fast"


def test_routing_is_deterministic():
    router = ConfiguredModelRouter([FAST_CHEAP, BALANCED, PREMIUM])
    first = router.route("t", quality_target=2, est_tokens_input=500, est_tokens_output=200)
    second = router.route("t", quality_target=2, est_tokens_input=500, est_tokens_output=200)
    assert first == second
