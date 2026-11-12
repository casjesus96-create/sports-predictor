"""Experimental NBA player Over/Under baseline from pregame historical samples.

This module is intentionally independent from NBA-1.1.0. It estimates empirical
frequencies only; it does not create picks, consume odds, or modify official predictions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Iterable

MIN_SAMPLE_DEFAULT = 5

MARKET_COMPONENTS = {
    "PTS": ("points",),
    "REB": ("rebounds",),
    "AST": ("assists",),
    "PRA": ("points", "rebounds", "assists"),
    "PR": ("points", "rebounds"),
    "PA": ("points", "assists"),
    "RA": ("rebounds", "assists"),
    "BLK": ("blocks",),
    "STL": ("steals",),
}


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _finite_stat(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def extract_pregame_market_observations(
    game_records: Iterable[dict],
    market: str,
    cutoff: object,
) -> dict:
    """Build a market series using completed games strictly before the target kickoff.

    Each record must contain game_id, kickoff, completed=True, and the required
    raw player stat fields. Missing components are excluded rather than treated
    as zero. Duplicate game IDs are counted once.
    """
    market_key = str(market or "").strip().upper()
    components = MARKET_COMPONENTS.get(market_key)
    if not components:
        return {"available": False, "reason": "UNSUPPORTED_MARKET", "market": market_key}

    cutoff_dt = _parse_datetime(cutoff)
    if cutoff_dt is None:
        return {"available": False, "reason": "INVALID_CUTOFF", "market": market_key}

    observations = []
    seen_game_ids = set()
    excluded = {
        "missing_game_id": 0,
        "duplicate_game": 0,
        "not_completed": 0,
        "missing_or_invalid_kickoff": 0,
        "at_or_after_cutoff": 0,
        "missing_or_invalid_stats": 0,
    }

    for record in game_records or []:
        if not isinstance(record, dict):
            excluded["missing_game_id"] += 1
            continue
        game_id = str(record.get("game_id") or "").strip()
        if not game_id:
            excluded["missing_game_id"] += 1
            continue
        if game_id in seen_game_ids:
            excluded["duplicate_game"] += 1
            continue
        seen_game_ids.add(game_id)

        if record.get("completed") is not True:
            excluded["not_completed"] += 1
            continue
        kickoff = _parse_datetime(record.get("kickoff"))
        if kickoff is None:
            excluded["missing_or_invalid_kickoff"] += 1
            continue
        if kickoff >= cutoff_dt:
            excluded["at_or_after_cutoff"] += 1
            continue

        values = [_finite_stat(record.get(component)) for component in components]
        if any(value is None for value in values):
            excluded["missing_or_invalid_stats"] += 1
            continue

        observations.append({
            "game_id": game_id,
            "kickoff": kickoff.isoformat(),
            "value": round(sum(values), 4),
        })

    observations.sort(key=lambda item: item["kickoff"], reverse=True)
    return {
        "available": bool(observations),
        "market": market_key,
        "components": list(components),
        "observations": observations,
        "sample_size": len(observations),
        "excluded": excluded,
        "cutoff": cutoff_dt.isoformat(),
    }


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


def evaluate_player_market(
    game_records: Iterable[dict],
    market: str,
    line: object,
    cutoff: object,
    *,
    min_sample: int = MIN_SAMPLE_DEFAULT,
) -> dict:
    """Evaluate a real supplied line against strictly pregame player game history."""
    history = extract_pregame_market_observations(game_records, market, cutoff)
    if not history.get("available"):
        return {
            "available": False,
            "reason": history.get("reason", "NO_VALID_HISTORICAL_OBSERVATIONS"),
            "market": history.get("market"),
            "sample_size": history.get("sample_size", 0),
            "excluded": history.get("excluded", {}),
        }

    result = evaluate_over_under(
        [item["value"] for item in history["observations"]],
        line,
        min_sample=min_sample,
    )
    result["market"] = history["market"]
    result["history_sample_size"] = history["sample_size"]
    result["excluded"] = history["excluded"]
    result["cutoff"] = history["cutoff"]
    if not result.get("available"):
        result["reason"] = result.get("reason", "INSUFFICIENT_SAMPLE")
    return result
