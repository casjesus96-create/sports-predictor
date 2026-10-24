"""Football Poisson goal-market engine.

Produces mathematical estimates from completed competition scores only. These
outputs are not calibrated probabilities or betting advice until evaluated with
chronological, immutable pre-match snapshots and a sufficiently large sample.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

MODEL_VERSION = "FOOTBALL-POISSON-0.3.0"
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
    full_time = ((match.get("score") or {}).get("fullTime") or {})
    hg, ag = full_time.get("home"), full_time.get("away")
    if not home or not away or not isinstance(hg, int) or not isinstance(ag, int):
        return None
    if hg < 0 or ag < 0:
        return None
    return str(home), str(away), hg, ag


def _fair_odds(probability: float) -> float | None:
    return round(1.0 / probability, 2) if probability > 0 else None


def predict_1x2(
    home_team: str,
    away_team: str,
    completed_matches: list[dict[str, Any]],
    *,
    home_advantage: float = 1.08,
) -> dict[str, Any]:
    """Estimate 1X2 and goal markets using independent Poisson score matrix."""
    if not home_team.strip() or not away_team.strip() or home_team == away_team:
        raise ValueError("Se requieren dos equipos distintos y nombres válidos.")
    if not 0.8 <= home_advantage <= 1.3:
        raise ValueError("home_advantage debe estar entre 0.8 y 1.3.")

    parsed = [row for match in completed_matches if (row := _match_goals(match))]
    if not parsed:
        return {"available": False, "reason": "No hay partidos finalizados válidos.", "model_version": MODEL_VERSION}

    league_home_avg = sum(h for _, _, h, _ in parsed) / len(parsed)
    league_away_avg = sum(a for _, _, _, a in parsed) / len(parsed)
    league_avg = max(0.2, (league_home_avg + league_away_avg) / 2)

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

    def rate(total: float, count: float, prior: float) -> float:
        return (total + prior * 4.0) / (count + 4.0)

    home_attack = rate(h["scored_home"], h["home_games"], league_home_avg)
    home_defence = rate(h["conceded_home"], h["home_games"], league_away_avg)
    away_attack = rate(a["scored_away"], a["away_games"], league_away_avg)
    away_defence = rate(a["conceded_away"], a["away_games"], league_home_avg)

    # Convert raw goal rates into dimensionless strengths before applying league baselines.
    home_attack_strength = home_attack / max(0.2, league_home_avg)
    home_defence_weakness = home_defence / max(0.2, league_away_avg)
    away_attack_strength = away_attack / max(0.2, league_away_avg)
    away_defence_weakness = away_defence / max(0.2, league_home_avg)
    expected_home = max(0.15, min(4.5, league_home_avg * home_attack_strength * away_defence_weakness * home_advantage))
    expected_away = max(0.15, min(4.5, league_away_avg * away_attack_strength * away_defence_weakness / home_advantage))

    home_pmf = [_poisson_pmf(expected_home, goals) for goals in range(MAX_GOALS + 1)]
    away_pmf = [_poisson_pmf(expected_away, goals) for goals in range(MAX_GOALS + 1)]
    matrix = [[home_pmf[hg] * away_pmf[ag] for ag in range(MAX_GOALS + 1)] for hg in range(MAX_GOALS + 1)]
    # Normalize the truncated score matrix so every market is internally consistent.
    matrix_total = sum(sum(row) for row in matrix)
    matrix = [[p / matrix_total for p in row] for row in matrix]

    home_win = sum(matrix[hg][ag] for hg in range(MAX_GOALS + 1) for ag in range(MAX_GOALS + 1) if hg > ag)
    draw = sum(matrix[g][g] for g in range(MAX_GOALS + 1))
    away_win = sum(matrix[hg][ag] for hg in range(MAX_GOALS + 1) for ag in range(MAX_GOALS + 1) if hg < ag)

    def total_goals_probability(predicate) -> float:
        return sum(matrix[hg][ag] for hg in range(MAX_GOALS + 1) for ag in range(MAX_GOALS + 1) if predicate(hg + ag))

    def home_goals_probability(predicate) -> float:
        return sum(matrix[hg][ag] for hg in range(MAX_GOALS + 1) for ag in range(MAX_GOALS + 1) if predicate(hg))

    def away_goals_probability(predicate) -> float:
        return sum(matrix[hg][ag] for hg in range(MAX_GOALS + 1) for ag in range(MAX_GOALS + 1) if predicate(ag))

    btts_yes = sum(matrix[hg][ag] for hg in range(1, MAX_GOALS + 1) for ag in range(1, MAX_GOALS + 1))
    btts_no = 1.0 - btts_yes
    total_expected = expected_home + expected_away
    scorelines = sorted(
        ((matrix[hg][ag], hg, ag) for hg in range(MAX_GOALS + 1) for ag in range(MAX_GOALS + 1)),
        reverse=True,
    )[:5]
    scorelines = [{"home": hg, "away": ag, "probability": round(p, 6)} for p, hg, ag in scorelines]

    def market(probability: float) -> dict[str, Any]:
        return {"probability": round(probability, 6), "fair_odds": _fair_odds(probability)}

    goal_totals = {
        "over_1_5": market(total_goals_probability(lambda n: n >= 2)),
        "under_1_5": market(total_goals_probability(lambda n: n <= 1)),
        "over_2_5": market(total_goals_probability(lambda n: n >= 3)),
        "under_2_5": market(total_goals_probability(lambda n: n <= 2)),
        "over_3_5": market(total_goals_probability(lambda n: n >= 4)),
        "under_3_5": market(total_goals_probability(lambda n: n <= 3)),
        "over_4_5": market(total_goals_probability(lambda n: n >= 5)),
        "under_4_5": market(total_goals_probability(lambda n: n <= 4)),
    }
    team_goals = {
        "home_over_0_5": market(home_goals_probability(lambda n: n >= 1)),
        "home_over_1_5": market(home_goals_probability(lambda n: n >= 2)),
        "home_over_2_5": market(home_goals_probability(lambda n: n >= 3)),
        "away_over_0_5": market(away_goals_probability(lambda n: n >= 1)),
        "away_over_1_5": market(away_goals_probability(lambda n: n >= 2)),
        "away_over_2_5": market(away_goals_probability(lambda n: n >= 3)),
    }
    probabilities = {"home": home_win, "draw": draw, "away": away_win}
    return {
        "available": True,
        "model_version": MODEL_VERSION,
        "home_team": home_team,
        "away_team": away_team,
        "probabilities": {key: round(value, 6) for key, value in probabilities.items()},
        "expected_goals": {"home": round(expected_home, 3), "away": round(expected_away, 3), "total": round(total_expected, 3)},
        "goal_markets": {
            "both_teams_to_score": {"yes": market(btts_yes), "no": market(btts_no)},
            "total_goals": goal_totals,
            "team_goals": team_goals,
            "clean_sheet": {
                "home": market(away_goals_probability(lambda n: n == 0)),
                "away": market(home_goals_probability(lambda n: n == 0)),
            },
        },
        "double_chance": {
            "home_or_draw": market(home_win + draw),
            "draw_or_away": market(draw + away_win),
            "home_or_away": market(home_win + away_win),
        },
        "most_likely_scorelines": scorelines,
        "sample": {
            "completed_matches_in_competition": len(parsed),
            "home_team_matches": int(h["games"]),
            "away_team_matches": int(a["games"]),
        },
        "method": "Distribución de Poisson independiente, tasas local/visitante y regresión a la media de la competición",
        "calibration": {
            "status": "not_calibrated",
            "note": "Las cuotas justas son inversos matemáticos de las probabilidades estimadas, no cuotas de mercado ni evidencia de valor esperado positivo.",
            "required_next_step": "Guardar snapshots prepartido inmutables y evaluar cronológicamente Brier, log loss, calibración y rendimiento contra cuotas históricas disponibles.",
        },
        "limitations": [
            "Estimación experimental; no calibrada ni validada como rentable.",
            "No incorpora alineaciones, lesiones, xG, descanso, forma ponderada ni cuotas de mercado.",
            "Las probabilidades de mercados derivados proceden de la misma matriz de goles; no son señales independientes.",
        ],
    }
