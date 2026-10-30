"""Metrics for evaluating experimental live MLB batter-hit probabilities.

This module evaluates saved/replayed point-in-time observations. It deliberately
does not fetch current season stats to score historical forecasts, since that
would introduce look-ahead leakage. Each row must contain a probability recorded
at a historical cutoff and the subsequent outcome.
"""
from __future__ import annotations

import math


def _probability(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def _binary(value):
    if value is True or value == 1:
        return 1
    if value is False or value == 0:
        return 0
    return None


def _score(probabilities, outcomes, bins=10):
    count = len(outcomes)
    if not count:
        return {
            "n": 0,
            "observed_hit_rate": None,
            "brier_score": None,
            "log_loss": None,
            "calibration": [],
        }
    epsilon = 1e-15
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / count
    log_loss = -sum(
        y * math.log(max(epsilon, p)) +
        (1 - y) * math.log(max(epsilon, 1 - p))
        for p, y in zip(probabilities, outcomes)
    ) / count
    calibration = []
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        indices = [
            i for i, p in enumerate(probabilities)
            if lower <= p < upper or (index == bins - 1 and p == 1.0)
        ]
        if not indices:
            continue
        calibration.append({
            "bin_start": round(lower, 2),
            "bin_end": round(upper, 2),
            "n": len(indices),
            "mean_predicted_probability": round(sum(probabilities[i] for i in indices) / len(indices), 6),
            "observed_hit_rate": round(sum(outcomes[i] for i in indices) / len(indices), 6),
        })
    return {
        "n": count,
        "observed_hit_rate": round(sum(outcomes) / count, 6),
        "brier_score": round(brier, 6),
        "log_loss": round(log_loss, 6),
        "calibration": calibration,
    }


def evaluate_live_hit_forecasts(rows, bins=10):
    """Evaluate future-hit forecasts and optional paired baseline probabilities.

    Required fields:
      - probability_additional_hit: probability recorded before the outcome
      - actual_additional_hit: whether a hit occurred after that cutoff

    Optional:
      - baseline_probability: paired season-AVG-only forecast at the same cutoff

    Rows with invalid probabilities/outcomes are excluded. The caller is
    responsible for ensuring timestamps/cutoffs precede outcomes and that
    features were available at the cutoff.
    """
    if not isinstance(bins, int) or bins < 1 or bins > 20:
        raise ValueError("bins debe ser un entero entre 1 y 20.")
    usable = []
    excluded = 0
    for row in rows or []:
        if not isinstance(row, dict):
            excluded += 1
            continue
        probability = _probability(row.get("probability_additional_hit"))
        outcome = _binary(row.get("actual_additional_hit"))
        if probability is None or outcome is None:
            excluded += 1
            continue
        usable.append((probability, outcome, _probability(row.get("baseline_probability"))))

    probabilities = [row[0] for row in usable]
    outcomes = [row[1] for row in usable]
    report = {
        "method": "experimental_live_additional_hit_backtest_v1",
        "n": len(usable),
        "excluded_rows": excluded,
        "primary": _score(probabilities, outcomes, bins),
        "baseline": None,
        "comparison": None,
        "limitations": [
            "La evaluación solo es válida si cada probabilidad fue registrada antes del resultado.",
            "No demuestra causalidad ni rentabilidad de apuestas.",
            "Las observaciones del mismo jugador o partido pueden estar correlacionadas.",
            "La calibración por intervalos es inestable con muestras pequeñas.",
        ],
    }
    paired = [
        (row[0], row[1], row[2])
        for row in usable
        if row[2] is not None
    ]
    if paired:
        baseline_probabilities = [row[2] for row in paired]
        paired_outcomes = [row[1] for row in paired]
        primary_paired = _score([row[0] for row in paired], paired_outcomes, bins)
        baseline = _score(baseline_probabilities, paired_outcomes, bins)
        report["baseline"] = baseline
        report["comparison"] = {
            "paired_n": len(paired),
            "primary_brier_minus_baseline": round(
                primary_paired["brier_score"] - baseline["brier_score"], 6
            ),
            "primary_log_loss_minus_baseline": round(
                primary_paired["log_loss"] - baseline["log_loss"], 6
            ),
            "interpretation": "Negativo favorece la proyección principal; positivo favorece el baseline.",
        }
    return report
