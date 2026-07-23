from __future__ import annotations

from megachud.routing.engine import ModelProfile
from megachud.routing.selector import ModelSelector

HAIKU = ModelProfile("claude-haiku-4-5-20251001", 0.001, 0.005, quality_tier=1, est_latency_ms=500)
SONNET = ModelProfile("claude-sonnet-5", 0.003, 0.015, quality_tier=2, est_latency_ms=1200)
OPUS = ModelProfile("claude-opus-4-8", 0.005, 0.025, quality_tier=3, est_latency_ms=2500)
PROFILES = [HAIKU, SONNET, OPUS]


def test_manual_override_wins():
    sel = ModelSelector(PROFILES, default_model="claude-haiku-4-5-20251001")
    model, reason = sel.select("anything", override="claude-opus-4-8")
    assert model == "claude-opus-4-8"
    assert reason == "manual override"


def test_unknown_override_falls_back_to_auto():
    sel = ModelSelector(PROFILES, default_model="claude-sonnet-5")
    model, reason = sel.select("short", override="gpt-4")
    assert model == "claude-sonnet-5"  # base tier for standard prompt
    assert "ignored unknown model" in reason


def test_auto_standard_prompt_uses_default_tier():
    sel = ModelSelector(PROFILES, default_model="claude-sonnet-5")
    model, reason = sel.select("write hello to a file")
    assert model == "claude-sonnet-5"
    assert "standard prompt" in reason


def test_auto_escalates_on_long_prompt():
    sel = ModelSelector(PROFILES, default_model="claude-sonnet-5")
    model, reason = sel.select("x" * 700)
    assert model == "claude-opus-4-8"  # escalated from tier 2 to tier 3
    assert "complex/long prompt" in reason


def test_auto_escalates_on_complexity_keyword():
    sel = ModelSelector(PROFILES, default_model="claude-haiku-4-5-20251001")
    model, reason = sel.select("please analyze and compare these approaches")
    assert model == "claude-sonnet-5"  # escalated from tier 1 to tier 2
    assert "complex/long prompt" in reason


def test_escalation_capped_at_top_tier():
    sel = ModelSelector(PROFILES, default_model="claude-opus-4-8")
    model, _ = sel.select("research and analyze in depth")
    assert model == "claude-opus-4-8"  # already top tier, stays


def test_no_profiles_falls_back_to_default():
    sel = ModelSelector([], default_model="claude-sonnet-5")
    model, reason = sel.select("anything")
    assert model == "claude-sonnet-5"
    assert "no routing profiles" in reason
