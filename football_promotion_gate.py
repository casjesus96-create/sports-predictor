"""Conservative promotion gate for football walk-forward candidates.

This module is deliberately separate from the official predictor. It only
interprets metrics produced by a leakage-safe chronological evaluation and never
changes model selection or writes prediction history.
"""
from __future__ import annotations

from typing import Any

DEFAULT_MIN_SAMPLE_SIZE = 250


def promotion_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> dict[str, Any]:
    """Return an auditable decision; lower Brier/log loss are better.

    A candidate is eligible for further review only when it has enough paired
    observations and improves both proper scoring rules. Eligibility is not
    automatic activation, nor evidence of betting profitability.
    """
    if min_sample_size < 1:
        raise ValueError("min_sample_size debe ser al menos 1.")

    try:
        baseline_n = int(baseline["sample_size"])
        candidate_n = int(candidate["sample_size"])
        baseline_brier = float(baseline["brier_score"])
        candidate_brier = float(candidate["brier_score"])
        baseline_log_loss = float(baseline["log_loss"])
        candidate_log_loss = float(candidate["log_loss"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return {
            "status": "INSUFFICIENT_METRICS",
            "eligible_for_review": False,
            "reason": "Faltan métricas válidas para comparar los modelos.",
        }

    if baseline_n != candidate_n:
        return {
            "status": "UNPAIRED_SAMPLE",
            "eligible_for_review": False,
            "reason": "Los modelos deben evaluarse sobre exactamente la misma muestra.",
            "baseline_sample_size": baseline_n,
            "candidate_sample_size": candidate_n,
        }

    if baseline_n < min_sample_size:
        return {
            "status": "INSUFFICIENT_SAMPLE",
            "eligible_for_review": False,
            "reason": f"La muestra debe alcanzar al menos {min_sample_size} partidos.",
            "sample_size": baseline_n,
            "minimum_sample_size": min_sample_size,
        }

    values = (baseline_brier, candidate_brier, baseline_log_loss, candidate_log_loss)
    if any(value < 0 or value != value or value in (float("inf"), float("-inf")) for value in values):
        return {
            "status": "INVALID_METRICS",
            "eligible_for_review": False,
            "reason": "Brier y Log Loss deben ser valores finitos y no negativos.",
        }

    brier_delta = candidate_brier - baseline_brier
    log_loss_delta = candidate_log_loss - baseline_log_loss
    improved_both = brier_delta < 0 and log_loss_delta < 0
    return {
        "status": "ELIGIBLE_FOR_REVIEW" if improved_both else "NO_PROMOTION",
        "eligible_for_review": improved_both,
        "reason": (
            "El candidato mejora ambos proper scoring rules en muestra emparejada; "
            "requiere revisión de calibración, segmentos y estabilidad antes de cualquier activación."
            if improved_both
            else "El candidato no mejora simultáneamente Brier y Log Loss."
        ),
        "sample_size": baseline_n,
        "minimum_sample_size": min_sample_size,
        "delta_candidate_minus_baseline": {
            "brier_score": round(brier_delta, 8),
            "log_loss": round(log_loss_delta, 8),
        },
        "official_model_unchanged": True,
        "automatic_activation": False,
        "profitability_claim": False,
    }
