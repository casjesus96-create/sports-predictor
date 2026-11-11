"""Read-only confidence calibration diagnostics for NBA official predictions."""
from __future__ import annotations

import math
from datetime import datetime, timezone


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



def build_temporal_calibration_stability(observations, minimum_per_window: int = 30):
    """Compare favorite calibration across two chronological, date-clustered windows."""
    by_date = {}
    excluded_missing_kickoff = 0
    excluded_invalid_observation = 0

    for item in observations or []:
        try:
            confidence = float(item.get("confidence"))
            correct = item.get("correct")
            kickoff = item.get("kickoff")
            if not math.isfinite(confidence) or not 0.5 <= confidence <= 0.95 or not isinstance(correct, bool):
                raise ValueError("invalid calibration observation")
            parsed = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                match_date = parsed.astimezone(timezone.utc).date().isoformat()
            else:
                match_date = parsed.date().isoformat()
        except (AttributeError, TypeError, ValueError, OverflowError):
            if not isinstance(item, dict) or not item.get("kickoff"):
                excluded_missing_kickoff += 1
            else:
                excluded_invalid_observation += 1
            continue
        by_date.setdefault(match_date, []).append({
            "confidence": confidence,
            "correct": correct,
        })

    ordered_dates = sorted(by_date)
    total = sum(len(by_date[date]) for date in ordered_dates)
    candidates = []
    left_count = 0
    for index, date in enumerate(ordered_dates[:-1], start=1):
        left_count += len(by_date[date])
        right_count = total - left_count
        if left_count >= minimum_per_window and right_count >= minimum_per_window:
            candidates.append((abs(left_count - right_count), index, left_count, right_count))

    base = {
        "sample_size": total,
        "minimum_per_window": int(minimum_per_window),
        "excluded_missing_kickoff": excluded_missing_kickoff,
        "excluded_invalid_observation": excluded_invalid_observation,
        "date_cluster": "Todos los partidos de una misma fecha UTC permanecen en la misma ventana.",
        "read_only": True,
        "official_probability_changed": False,
    }
    if not candidates:
        return {
            **base,
            "eligible": False,
            "windows": [],
            "reason": (
                f"Se requieren al menos {minimum_per_window} observaciones válidas en cada ventana "
                "y partidos en al menos dos fechas distintas."
            ),
        }

    _, split_index, _, _ = min(candidates)
    windows = (
        ("earlier", ordered_dates[:split_index]),
        ("later", ordered_dates[split_index:]),
    )
    summaries = []
    for label, dates in windows:
        items = [item for date in dates for item in by_date[date]]
        count = len(items)
        wins = sum(item["correct"] for item in items)
        mean_confidence = sum(item["confidence"] for item in items) / count
        observed_accuracy = wins / count
        summaries.append({
            "period": label,
            "sample_size": count,
            "start_date": dates[0],
            "end_date": dates[-1],
            "mean_confidence": round(mean_confidence, 4),
            "observed_accuracy": round(observed_accuracy, 4),
            "calibration_error": round(observed_accuracy - mean_confidence, 4),
            "accuracy_ci_95": wilson_interval(wins, count),
            "brier_score": round(
                sum((item["confidence"] - float(item["correct"])) ** 2 for item in items) / count,
                6,
            ),
        })

    return {
        **base,
        "eligible": True,
        "split_before": ordered_dates[split_index],
        "windows": summaries,
        "reason": None,
    }
