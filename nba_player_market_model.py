"""Experimental NBA player Over/Under baseline from pregame historical samples.

This module is intentionally independent from NBA-1.1.0. It estimates empirical
frequencies only; it does not create picks, consume odds, or modify official predictions.
"""
from __future__ import annotations

import math
from typing import Iterable

MIN_SAMPLE_DEFAULT = 5


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054):
    if total <= 0:
        return None
    rate = successes / total
    denominator = 1.0 + z * z / total
    center = (rate + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt((rate * (1.0 - rate) / total) + z * z / (4.0 * total * total)) / denominator
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def evaluate_over_under(
    observations: Iterable[object],
    line: object,
    *,
    min_sample: int = MIN_SAMPLE_DEFAULT,
) -> dict:
    """Estimate Over/Under/Push probabilities from prior player game results.

    Pushes are reported separately. Over/Under are smoothed with a Beta(1, 1)
    prior among non-push outcomes, then scaled by the observed non-push share.
    Wilson intervals describe the unsmoothed conditional hit rate and are also
    scaled by the non-push share. No normality assumption is made.
    """
    try:
        numeric_line = float(line)
        minimum = max(1, int(min_sample))
    except (TypeError, ValueError, OverflowError):
        return {"available": False, "reason": "INVALID_LINE_OR_MINIMUM"}

    if not math.isfinite(numeric_line) or numeric_line < 0:
        return {"available": False, "reason": "INVALID_LINE_OR_MINIMUM"}

    values = []
    for raw in observations or []:
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(value) and value >= 0:
            values.append(value)

    sample = len(values)
    if sample < minimum:
        return {
            "available": False,
            "reason": "INSUFFICIENT_SAMPLE",
            "sample_size": sample,
            "minimum_sample": minimum,
            "line": numeric_line,
        }

    over_count = sum(value > numeric_line for value in values)
    under_count = sum(value < numeric_line for value in values)
    push_count = sample - over_count - under_count
    decisive = over_count + under_count
    push_probability = push_count / sample

    if decisive:
        conditional_over = (over_count + 1.0) / (decisive + 2.0)
        conditional_under = (under_count + 1.0) / (decisive + 2.0)
        over_probability = (1.0 - push_probability) * conditional_over
        under_probability = (1.0 - push_probability) * conditional_under
        over_interval = _wilson_interval(over_count, decisive)
        under_interval = _wilson_interval(under_count, decisive)
        over_interval = [round(x * (1.0 - push_probability), 4) for x in over_interval]
        under_interval = [round(x * (1.0 - push_probability), 4) for x in under_interval]
    else:
        over_probability = under_probability = 0.0
        over_interval = under_interval = [0.0, 0.0]

    return {
        "available": True,
        "method": "EMPIRICAL_BETA_SMOOTHED",
        "sample_size": sample,
        "decisive_sample_size": decisive,
        "minimum_sample": minimum,
        "line": numeric_line,
        "over": {"count": over_count, "probability": round(over_probability, 4), "wilson_interval_95": over_interval},
        "under": {"count": under_count, "probability": round(under_probability, 4), "wilson_interval_95": under_interval},
        "push": {"count": push_count, "probability": round(push_probability, 4)},
        "limitations": [
            "Frecuencia histórica descriptiva; no ajusta por minutos, lesiones, titularidad ni rival.",
            "La probabilidad no equivale a una recomendación ni incorpora cuotas.",
            "El intervalo Wilson refleja incertidumbre de la tasa observada, no garantiza rendimiento futuro.",
        ],
    }
