from __future__ import annotations

from megachud.routing.engine import ModelProfile

__all__ = ["ModelSelector"]

# Words that suggest the request needs real reasoning, not a quick reply —
# used only to decide whether to escalate one quality tier. Deliberately a
# small, transparent list; this is a heuristic, not a classifier.
_COMPLEXITY_KEYWORDS = (
    "analyze",
    "analyse",
    "research",
    "compare",
    "design",
    "synthesize",
    "synthesise",
    "evaluate",
    "comprehensive",
    "in depth",
    "in-depth",
    "step by step",
    "step-by-step",
    "plan ",
    "strategy",
    "architecture",
    "debug",
    "refactor",
)
_LONG_PROMPT_CHARS = 600


class ModelSelector:
    """Chooses which model an interactive consumer (conversation, planner)
    actually calls. Two ways to decide, in priority order:

    1. Manual override — a caller-supplied model name (from the dashboard
       dropdown / API `model` field). If it's a configured profile, it
       wins outright.
    2. Smarter auto — a boring, transparent heuristic: start at the
       consumer's configured default tier and escalate one tier for a
       long or complexity-keyword-bearing prompt. Never silently
       downgrades below the consumer's default, so a short-but-important
       message still gets at least the default model.

    Returns (model_name, reason) so the reason can be surfaced to the user
    and recorded as a thought. Pure config + string logic — no LLM call.
    """

    def __init__(self, profiles: list[ModelProfile], default_model: str) -> None:
        self._by_name = {p.name: p for p in profiles}
        self._default_model = default_model
        # cheapest (by input cost) profile at each quality tier
        self._by_tier: dict[int, ModelProfile] = {}
        for p in sorted(profiles, key=lambda x: x.cost_per_1k_input_tokens):
            self._by_tier.setdefault(p.quality_tier, p)
        self._max_tier = max((p.quality_tier for p in profiles), default=0)

    def select(self, prompt: str, override: str | None = None) -> tuple[str, str]:
        note = ""
        if override:
            if override in self._by_name:
                return override, "manual override"
            note = f"ignored unknown model {override!r}; "

        # No profiles configured (e.g. a bare test settings) — fall back to
        # the consumer's fixed default with an honest reason.
        if not self._by_tier or self._default_model not in self._by_name:
            return self._default_model, note + "default (no routing profiles)"

        base_tier = self._by_name[self._default_model].quality_tier
        if self._is_complex(prompt):
            tier = min(base_tier + 1, self._max_tier)
            why = "complex/long prompt"
        else:
            tier = base_tier
            why = "standard prompt"

        chosen = self._at_or_below(tier)
        return chosen.name, note + f"auto: {why} → {chosen.name}"

    def _is_complex(self, prompt: str) -> bool:
        if len(prompt) > _LONG_PROMPT_CHARS:
            return True
        lowered = prompt.lower()
        return any(kw in lowered for kw in _COMPLEXITY_KEYWORDS)

    def _at_or_below(self, tier: int) -> ModelProfile:
        # Exact tier if present, else the highest available tier <= target
        # (profiles may not be perfectly contiguous).
        for t in range(tier, -1, -1):
            if t in self._by_tier:
                return self._by_tier[t]
        # tier below everything configured — take the lowest available
        return self._by_tier[min(self._by_tier)]
