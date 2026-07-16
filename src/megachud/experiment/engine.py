from __future__ import annotations

import json
import statistics as stats  # only mean() — no significance testing, deliberately boring

from sqlalchemy.orm import Session, sessionmaker

from megachud.models.experiment import Experiment, ExperimentRecommendation, ExperimentStatus
from megachud.strategy.metrics import outcomes_for_strategy
from megachud.strategy.promotion import propose_promotion


def _summarize(outcomes: list[dict]) -> dict:
    n = len(outcomes)
    return {
        "n": n,
        "success_rate": sum(o["success"] for o in outcomes) / n if n else 0.0,
        "mean_duration_ms": stats.mean(o["duration_ms"] for o in outcomes) if n else 0.0,
    }


def evaluate_experiment(session_factory: sessionmaker[Session], experiment_id: str) -> Experiment:
    """Deterministic: success-rate delta + minimum-sample-size gate, no
    significance testing (spec asks for "measurable," not "statistically
    significant"). If both arms have >= minimum_sample_size outcomes:
    delta > 0 => CONCLUDED/PROMOTE_VARIANT (also creates a PromotionRequest
    via propose_promotion — human review still required, nothing
    auto-applied); delta <= 0 => CONCLUDED/KEEP_CONTROL. Below the
    threshold: recommendation = INSUFFICIENT_DATA, status stays RUNNING.
    Called explicitly (route or script) — never auto-triggered; no
    background polling loop exists anywhere in this codebase.
    """
    session = session_factory()
    try:
        experiment = session.get(Experiment, experiment_id)
        if experiment is None:
            raise KeyError(f"unknown experiment: {experiment_id!r}")

        control = _summarize(outcomes_for_strategy(session, experiment.control_strategy_id))
        variant = _summarize(outcomes_for_strategy(session, experiment.variant_strategy_id))

        result = {
            "control": control,
            "variant": variant,
            "success_rate_delta": variant["success_rate"] - control["success_rate"],
        }
        experiment.result_json = json.dumps(result)

        enough_data = (
            control["n"] >= experiment.minimum_sample_size and variant["n"] >= experiment.minimum_sample_size
        )
        if enough_data:
            experiment.status = ExperimentStatus.CONCLUDED
            experiment.recommendation = (
                ExperimentRecommendation.PROMOTE_VARIANT
                if result["success_rate_delta"] > 0
                else ExperimentRecommendation.KEEP_CONTROL
            )
        else:
            experiment.recommendation = ExperimentRecommendation.INSUFFICIENT_DATA

        session.commit()
        session.refresh(experiment)
        experiment_id_, recommendation = experiment.id, experiment.recommendation
        session.expunge(experiment)
    finally:
        session.close()

    if recommendation == ExperimentRecommendation.PROMOTE_VARIANT:
        propose_promotion(session_factory, experiment_id_)

    return experiment
