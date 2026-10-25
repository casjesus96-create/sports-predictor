"""Shadow-only H2H adjustment experiment for football 1X2 probabilities.

This module is deliberately not imported by football_api.py and cannot alter the
official FOOTBALL-POISSON model or its immutable snapshots. H2H outcomes are
filtered to valid, completed meetings strictly before the target kickoff.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

EXPERIMENT_VERSION = "FOOTBALL-H2H-SHADOW-0.1.0"
DEFAULT_MAX_H2H_WEIGHT = 0.20
DEFAULT_PRIOR_MEETINGS = 8.0
MIN_H2H_MEETINGS = 3


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _valid_score(match: dict[str, Any]) -> tuple[int, int] | None:
    if str(match.get("status", "")).upper() != "FINISHED":
        return None
    full_time = ((match.get("score") or {}).get("fullTime") or {})
    home, away = full_time.get("home"), full_time.get("away")
    if (not isinstance(home, int) or isinstance(home, bool)
            or not isinstance(away, int) or isinstance(away, bool)
            or home < 0 or away < 0):
        return None
    return home, away


def evaluate_h2h_candidate(
    home_team: str,
    away_team: str,
    kickoff_at: str,
    base_prediction: dict[str, Any],
    h2h_matches: list[dict[str, Any]],
    *,
    max_h2h_weight: float = DEFAULT_MAX_H2H_WEIGHT,
    prior_meetings: float = DEFAULT_PRIOR_MEETINGS,
    min_meetings: int = MIN_H2H_MEETINGS,
) -> dict[str, Any]:
    """Return shadow 1X2 probabilities blended with shrunk pre-kickoff H2H rates.

    The H2H component's influence is capped and shrunk toward zero for small
    samples. This is a testable candidate, not a calibrated or activated model.
    """
    if not home_team.strip() or not away_team.strip() or home_team.casefold() == away_team.casefold():
        raise ValueError("Se requieren dos equipos distintos y nombres válidos.")
    if not 0.0 <= max_h2h_weight <= 0.5:
        raise ValueError("max_h2h_weight debe estar entre 0 y 0.5.")
    if prior_meetings <= 0 or min_meetings < 1:
        raise ValueError("Los parámetros de regularización deben ser positivos.")
    kickoff = _parse_datetime(kickoff_at)
    if kickoff is None:
        raise ValueError("kickoff_at debe ser una fecha ISO 8601 con zona horaria.")

    if not base_prediction.get("available"):
        return {"available": False, "reason": "La predicción base no está disponible.",
                "experiment_version": EXPERIMENT_VERSION}
    raw_base = base_prediction.get("probabilities") or {}
    keys = ("home", "draw", "away")
    try:
        base = {key: float(raw_base[key]) for key in keys}
    except (KeyError, TypeError, ValueError):
        return {"available": False, "reason": "La predicción base no contiene probabilidades 1X2 válidas.",
                "experiment_version": EXPERIMENT_VERSION}
    if any(not math.isfinite(value) or value < 0 or value > 1 for value in base.values()):
        return {"available": False, "reason": "La predicción base contiene probabilidades fuera de rango.",
                "experiment_version": EXPERIMENT_VERSION}
    base_total = sum(base.values())
    if base_total <= 0:
        return {"available": False, "reason": "La suma de probabilidades base debe ser positiva.",
                "experiment_version": EXPERIMENT_VERSION}
    base = {key: value / base_total for key, value in base.items()}

    home_key, away_key = home_team.casefold(), away_team.casefold()
    seen: set[tuple[Any, ...]] = set()
    outcomes = {"home": 0, "draw": 0, "away": 0}
    valid_meetings = 0
    excluded_future = 0
    for match in h2h_matches:
        score = _valid_score(match)
        match_date = _parse_datetime(match.get("utcDate") or match.get("date"))
        if score is None or match_date is None:
            continue
        if match_date >= kickoff:
            excluded_future += 1
            continue
        match_home = str((match.get("homeTeam") or {}).get("name") or "").strip()
        match_away = str((match.get("awayTeam") or {}).get("name") or "").strip()
        if not match_home or not match_away:
            continue
        pair = {match_home.casefold(), match_away.casefold()}
        if pair != {home_key, away_key}:
            continue
        identity = match.get("id")
        dedupe_key = ("id", identity) if identity is not None else (
            "fixture", match_date.isoformat(), match_home.casefold(), match_away.casefold(), score
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        valid_meetings += 1
        hg, ag = score
        if match_home.casefold() == home_key:
            target_home_score, target_away_score = hg, ag
        else:
            target_home_score, target_away_score = ag, hg
        if target_home_score > target_away_score:
            outcomes["home"] += 1
        elif target_home_score < target_away_score:
            outcomes["away"] += 1
        else:
            outcomes["draw"] += 1

    if valid_meetings < min_meetings or max_h2h_weight == 0:
        return {
            "available": True,
            "experiment_version": EXPERIMENT_VERSION,
            "status": "INSUFFICIENT_H2H" if valid_meetings < min_meetings else "ZERO_WEIGHT",
            "base_probabilities": {key: round(value, 6) for key, value in base.items()},
            "candidate_probabilities": {key: round(value, 6) for key, value in base.items()},
            "h2h": {"valid_meetings": valid_meetings, "outcomes": outcomes,
                    "excluded_at_or_after_kickoff": excluded_future},
            "h2h_weight": 0.0,
            "note": "Sin ajuste H2H: muestra insuficiente o peso experimental desactivado.",
        }

    empirical = {key: outcomes[key] / valid_meetings for key in keys}
    weight = max_h2h_weight * valid_meetings / (valid_meetings + prior_meetings)
    candidate = {key: (1.0 - weight) * base[key] + weight * empirical[key] for key in keys}
    total = sum(candidate.values())
    candidate = {key: candidate[key] / total for key in keys}
    return {
        "available": True,
        "experiment_version": EXPERIMENT_VERSION,
        "status": "SHADOW_ONLY",
        "base_probabilities": {key: round(value, 6) for key, value in base.items()},
        "candidate_probabilities": {key: round(value, 6) for key, value in candidate.items()},
        "h2h": {
            "valid_meetings": valid_meetings,
            "outcomes": outcomes,
            "empirical_rates": {key: round(value, 6) for key, value in empirical.items()},
            "excluded_at_or_after_kickoff": excluded_future,
        },
        "h2h_weight": round(weight, 6),
        "parameters": {
            "max_h2h_weight": max_h2h_weight,
            "prior_meetings": prior_meetings,
            "min_meetings": min_meetings,
        },
        "note": "Solo evaluación sombra; no sustituye ni modifica el modelo oficial ni otros mercados.",
    }
