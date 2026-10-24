"""Experimental, deterministic football 1X2 engine based on recent league scores.

This module is intentionally pure: it does not call APIs, persist predictions, or
claim calibration/profitability. It consumes completed matches supplied by the caller.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

MODEL_VERSION = "FOOTBALL-POISSON-0.1.0"
MAX_GOALS = 10
MIN_TEAM_MATCHES = 3


def _poisson_pmf(rate: float, goals: int) -> float:
    if rate <= 0:
        return 1.0 if goals == 0 else 0.0
    return math.exp(-rate) * (rate ** goals) / math.factorial(goals)


def _match_goals(match: dict[str, Any]) -> tuple[str, str, int, int] | None:
    if str(match.get("status", "")).upper() != "FINISHED":
        return None
    home = (match.get("homeTeam") or {}).get("name")
    away = (match.get("awayTeam") or {}).get("name")
    score = match.get("score") or {}
    full_time = score.get("fullTime") or {}
    home_goals, away_goals = full_time.get("home"), full_time.get("away")
    if not home or not away or not isinstance(home_goals, int) or not isinstance(away_goals, int):
        return None
    if home_goals < 0 or away_goals < 0:
        return None
    return str(home), str(away), home_goals, away_goals


def predict_1x2(
    home_team: str,
    away_team: str,
    completed_matches: list[dict[str, Any]],
    *,
    home_advantage: float = 1.08,
) -> dict[str, Any]:
    """Estimate home/draw/away probabilities from finished matches only.

    Team scoring/conceding rates are shrunk toward league averages. Returns
    unavailable when either side has too little completed-match history.
    """
    if not home_team.strip() or not away_team.strip() or home_team == away_team:
        raise ValueError("Se requieren dos equipos distintos y nombres válidos.")
    if not 0.8 <= home_advantage <= 1.3:
        raise ValueError("home_advantage debe estar entre 0.8 y 1.3.")

    parsed = [row for match in completed_matches if (row := _match_goals(match))]
    if not parsed:
        return {"available": False, "reason": "No hay partidos finalizados válidos.", "model_version": MODEL_VERSION}

    total_goals = sum(h + a for _, _, h, a in parsed)
    league_home_avg = sum(h for _, _, h, _ in parsed) / len(parsed)
    league_away_avg = sum(a for _, _, _, a in parsed) / len(parsed)
    league_avg = max(0.2, total_goals / (2 * len(parsed)))

    stats: dict[str, dict[str, float]] = defaultdict(lambda: {
        "scored_home": 0, "conceded_home": 0, "home_games": 0,
        "scored_away": 0, "conceded_away": 0, "away_games": 0,
        "scored": 0, "conceded": 0, "games": 0,
    })
    for home, away, hg, ag in parsed:
        hs, aws = stats[home], stats[away]
        hs["scored_home"] += hg; hs["conceded_home"] += ag; hs["home_games"] += 1
        aws["scored_away"] += ag; aws["conceded_away"] += hg; aws["away_games"] += 1
        hs["scored"] += hg; hs["conceded"] += ag; hs["games"] += 1
        aws["scored"] += ag; aws["conceded"] += hg; aws["games"] += 1

    h, a = stats[home_team], stats[away_team]
    if h["games"] < MIN_TEAM_MATCHES or a["games"] < MIN_TEAM_MATCHES:
        return {
            "available": False,
            "reason": f"Se requieren al menos {MIN_TEAM_MATCHES} partidos finalizados por equipo.",
            "home_matches": int(h["games"]), "away_matches": int(a["games"]),
            "model_version": MODEL_VERSION,
        }

    # Shrink overall rates toward league average to limit extreme estimates
    # with small samples; use home/away splits only when there is evidence.
    def rate(total: float, count: float, prior: float) -> float:
        return (total + prior * 4.0) / (count + 4.0)

    home_attack = rate(h["scored_home"], h["home_games"], league_home_avg)
    home_defence = rate(h["conceded_home"], h["home_games"], league_away_avg)
    away_attack = rate(a["scored_away"], a["away_games"], league_away_avg)
    away_defence = rate(a["conceded_away"], a["away_games"], league_home_avg)

    expected_home = max(0.15, min(4.5, league_avg * (home_attack / max(0.2, league_home_avg)) * (away_defence / max(0.2, league_home_avg)) * home_advantage))
    expected_away = max(0.15, min(4.5, league_avg * (away_attack / max(0.2, league_away_avg)) * (home_defence / max(0.2, league_away_avg)) / home_advantage))

    home_win = draw = away_win = 0.0
    for hg in range(MAX_GOALS + 1):
        ph = _poisson_pmf(expected_home, hg)
        for ag in range(MAX_GOALS + 1):
            probability = ph * _poisson_pmf(expected_away, ag)
            if hg > ag:
                home_win += probability
            elif hg == ag:
                draw += probability
            else:
                away_win += probability
    total = home_win + draw + away_win
    probs = [home_win / total, draw / total, away_win / total]
    return {
        "available": True,
        "model_version": MODEL_VERSION,
        "home_team": home_team,
        "away_team": away_team,
        "probabilities": {
            "home": round(probs[0], 6),
            "draw": round(probs[1], 6),
            "away": round(probs[2], 6),
        },
        "expected_goals": {
            "home": round(expected_home, 3),
            "away": round(expected_away, 3),
        },
        "sample": {
            "completed_matches_in_competition": len(parsed),
            "home_team_matches": int(h["games"]),
            "away_team_matches": int(a["games"]),
        },
        "method": "Poisson de goles con tasas de ataque/defensa y regresión a la media de la liga",
        "limitations": [
            "Prototipo experimental no calibrado.",
            "No incorpora alineaciones, lesiones, xG ni cuotas.",
            "No debe interpretarse como recomendación de apuesta.",
        ],
    }
