"""Read-only confidence calibration diagnostics for NBA official predictions."""
from __future__ import annotations

import math


def wilson_interval(successes: int, sample_size: int, z: float = 1.959963984540054):
    """Return a rounded 95% Wilson score interval for an observed rate."""
    if sample_size <= 0:
        return None
    rate = successes / sample_size
    z2 = z * z
    denominator = 1.0 + z2 / sample_size
    center = (rate + z2 / (2.0 * sample_size)) / denominator
    margin = z * math.sqrt(rate * (1.0 - rate) / sample_size + z2 / (4.0 * sample_size * sample_size)) / denominator
    return {"lower": round(max(0.0, center - margin), 4), "upper": round(min(1.0, center + margin), 4)}


def build_confidence_calibration(observations, minimum_sample: int = 30):
    """Summarize correctness by predicted favorite confidence; never recalibrates."""
    bins = (
        (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
        (0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 0.90),
        (0.90, 0.950001),
    )
    valid = []
    for item in observations or []:
        try:
            confidence = float(item.get("confidence"))
        except (AttributeError, TypeError, ValueError):
            continue
        if not math.isfinite(confidence) or not 0.5 <= confidence <= 0.95:
            continue
        valid.append({"confidence": confidence, "correct": bool(item.get("correct"))})
    correct = sum(item["correct"] for item in valid)
    calibration = []
    for low, high in bins:
        bucket = [item for item in valid if low <= item["confidence"] < high]
        if not bucket:
            continue
        wins = sum(item["correct"] for item in bucket)
        count = len(bucket)
        observed = wins / count
        average = sum(item["confidence"] for item in bucket) / count
        calibration.append({
            "range": f"{low:.0%}-{min(high, 0.95):.0%}",
            "min": low, "max": min(high, 0.95), "sample_size": count,
            "mean_confidence": round(average, 4), "observed_accuracy": round(observed, 4),
            "calibration_error": round(observed - average, 4),
            "accuracy_ci_95": wilson_interval(wins, count), "small_sample": count < 10,
        })
    size = len(valid)
    return {
        "sample_size": size, "minimum_sample_required": int(minimum_sample),
        "calibration_ready": size >= int(minimum_sample),
        "observed_accuracy": round(correct / size, 4) if size else None,
        "accuracy_ci_95": wilson_interval(correct, size), "bins": calibration,
        "method": "favorite_confidence_buckets_wilson_95", "read_only": True,
        "official_probability_changed": False,
        "message": (
            "Muestra suficiente para estudiar calibración; no autoriza por sí sola una recalibración."
            if size >= int(minimum_sample)
            else f"Muestra insuficiente: se requieren {int(minimum_sample)} predicciones válidas; no se ajusta el modelo."
        ),
    }
