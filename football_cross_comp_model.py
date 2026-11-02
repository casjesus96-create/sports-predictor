"""Cross-competition football form candidate (shadow only).

Each team's recent scores are normalized by the scoring environment of the
competition in which each match was played. This module never changes the
official Poisson model or writes official snapshots.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

EXPERIMENT_VERSION = "FOOTBALL-CROSSCOMP-SHADOW-0.1.0"
MAX_GOALS = 10
MIN_TEAM_MATCHES = 5
MAX_RECENT_MATCHES = 12
PRIOR_MATCH_EQUIVALENT = 6.0


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def _score(match: dict[str, Any]) -> tuple[int, int] | None:
    if str(match.get("status", "")).upper() != "FINISHED":
        return None
    full = ((match.get("score") or {}).get("fullTime") or {})
    home, away = full.get("home"), full.get("away")
    if (not isinstance(home, int) or isinstance(home, bool) or home < 0
            or not isinstance(away, int) or isinstance(away, bool) or away < 0):
        return None
    return home, away


def _pmf(rate: float, goals: int) -> float:
    return math.exp(-rate) * rate ** goals / math.factorial(goals) if rate > 0 else (1.0 if goals == 0 else 0.0)


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    return {"available": False, "reason": reason, "model_version": EXPERIMENT_VERSION, **extra}


def predict_cross_competition(
    home_team_id: int,
    away_team_id: int,
    home_team: str,
    away_team: str,
    kickoff_at: str,
    home_history: list[dict[str, Any]],
    away_history: list[dict[str, Any]],
    competition_baselines: dict[str, dict[str, float]],
    target_competition: str,
) -> dict[str, Any]:
    """Build a normalized recent-form estimate from matches strictly pre-kickoff."""
    kickoff = _date(kickoff_at)
    if kickoff is None:
        return _unavailable("La fecha de inicio no contiene una zona horaria válida.")
    if home_team_id == away_team_id or not home_team.strip() or not away_team.strip():
        return _unavailable("Los identificadores o nombres de los equipos no son válidos.")

    target = target_competition.upper()
    target_base = competition_baselines.get(target)
    if not target_base or target_base.get("home", 0) <= 0 or target_base.get("away", 0) <= 0:
        return _unavailable("No existe una media goleadora verificable para la competición objetivo.")

    def team_rates(rows: list[dict[str, Any]], team_id: int):
        valid = []
        for match in rows:
            dt = _date(match.get("utcDate") or match.get("date"))
            score = _score(match)
            comp = str(((match.get("competition") or {}).get("code")) or "").upper()
            baseline = competition_baselines.get(comp)
            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}
            if dt is None or dt >= kickoff or score is None or not baseline:
                continue
            if home.get("id") == team_id:
                gf, ga = score
                expected_for, expected_against = baseline["home"], baseline["away"]
            elif away.get("id") == team_id:
                gf, ga = score[1], score[0]
                expected_for, expected_against = baseline["away"], baseline["home"]
            else:
                continue
            if expected_for <= 0 or expected_against <= 0:
                continue
            valid.append((dt, gf / expected_for, ga / expected_against, comp))
        valid.sort(key=lambda row: row[0], reverse=True)
        return valid[:MAX_RECENT_MATCHES]

    home_rows = team_rates(home_history, home_team_id)
    away_rows = team_rates(away_history, away_team_id)
    if len(home_rows) < MIN_TEAM_MATCHES or len(away_rows) < MIN_TEAM_MATCHES:
        return _unavailable(
            f"Se requieren al menos {MIN_TEAM_MATCHES} partidos recientes normalizables por equipo.",
            sample={"home_matches": len(home_rows), "away_matches": len(away_rows)},
        )

    # Shrink normalized attack/defence indices toward league-average strength (1.0).
    def index(rows: list[tuple], field: int) -> float:
        total = sum(row[field] for row in rows)
        return (total + PRIOR_MATCH_EQUIVALENT) / (len(rows) + PRIOR_MATCH_EQUIVALENT)

    home_attack = index(home_rows, 1)
    home_defence = index(home_rows, 2)
    away_attack = index(away_rows, 1)
    away_defence = index(away_rows, 2)
    expected_home = max(0.15, min(4.5, target_base["home"] * home_attack * away_defence))
    expected_away = max(0.15, min(4.5, target_base["away"] * away_attack * home_defence))

    home_p = [_pmf(expected_home, n) for n in range(MAX_GOALS + 1)]
    away_p = [_pmf(expected_away, n) for n in range(MAX_GOALS + 1)]
    matrix = [[home_p[h] * away_p[a] for a in range(MAX_GOALS + 1)] for h in range(MAX_GOALS + 1)]
    total = sum(map(sum, matrix))
    matrix = [[value / total for value in row] for row in matrix]
    probabilities = {
        "home": sum(matrix[h][a] for h in range(MAX_GOALS + 1) for a in range(MAX_GOALS + 1) if h > a),
        "draw": sum(matrix[g][g] for g in range(MAX_GOALS + 1)),
        "away": sum(matrix[h][a] for h in range(MAX_GOALS + 1) for a in range(MAX_GOALS + 1) if h < a),
    }
    return {
        "available": True,
        "status": "SHADOW_ONLY",
        "model_version": EXPERIMENT_VERSION,
        "home_team": home_team,
        "away_team": away_team,
        "probabilities": {key: round(value, 6) for key, value in probabilities.items()},
        "expected_goals": {
            "home": round(expected_home, 3),
            "away": round(expected_away, 3),
            "total": round(expected_home + expected_away, 3),
        },
        "sample": {
            "home_matches": len(home_rows),
            "away_matches": len(away_rows),
            "max_recent_matches": MAX_RECENT_MATCHES,
            "normalization": "goals scored/conceded divided by venue-specific competition averages",
            "competitions_used": sorted({row[3] for row in home_rows + away_rows}),
            "target_competition": target,
            "future_matches_excluded": True,
        },
        "method": "Poisson independiente con índices de ataque/defensa normalizados por competición y regresión a la media.",
        "calibration": {"status": "not_calibrated", "note": "Candidato experimental; requiere backtest walk-forward antes de cualquier promoción."},
    }
