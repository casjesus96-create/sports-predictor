"""Highlightly-derived experimental football model. Never used by the official predictor."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

MODEL_VERSION = "FOOTBALL-HIGHLIGHTLY-SHADOW-0.1.0"


def _score(value: Any):
    if not isinstance(value, str):
        return None
    parts = value.replace(":", "-").split("-")
    if len(parts) != 2:
        return None
    try:
        home, away = int(parts[0].strip()), int(parts[1].strip())
        return (home, away) if home >= 0 and away >= 0 else None
    except (TypeError, ValueError):
        return None


def _date(value: Any):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def _recent_rates(rows: Any, team_id: int):
    scored, conceded = [], []
    if not isinstance(rows, list):
        return None
    valid = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        state = str((item.get("state") or {}).get("description") or "").casefold()
        if not state.startswith("finished") and state != "awarded":
            continue
        score = _score(((item.get("state") or {}).get("score") or {}).get("current"))
        home, away = item.get("homeTeam") or {}, item.get("awayTeam") or {}
        if not score or team_id not in (home.get("id"), away.get("id")):
            continue
        valid.append((item, score, home, away))
    valid.sort(key=lambda row: str(row[0].get("date") or ""), reverse=True)
    for item, (hg, ag), home, away in valid[:5]:
        if home.get("id") == team_id:
            scored.append(hg); conceded.append(ag)
        else:
            scored.append(ag); conceded.append(hg)
    if not scored:
        return None
    return {"goals_for": sum(scored) / len(scored), "goals_against": sum(conceded) / len(conceded), "sample": len(scored)}


def _league_row(rows: Any, league_id: Any):
    if not isinstance(rows, list):
        return None
    candidates = [row for row in rows if isinstance(row, dict) and row.get("leagueId") == league_id]
    if not candidates:
        return None
    candidates.sort(key=lambda row: int(row.get("season") or 0), reverse=True)
    return candidates[0]


def _rate(stats: dict, venue: str, metric: str):
    section = stats.get(venue) or {}
    games = section.get("games") or {}
    goals = section.get("goals") or {}
    played = games.get("played")
    value = goals.get(metric)
    if not isinstance(played, (int, float)) or played <= 0 or not isinstance(value, (int, float)):
        return None
    return float(value) / float(played)


def _poisson(rate: float, goals: int):
    return math.exp(-rate) * rate ** goals / math.factorial(goals)


def predict_highlightly_shadow(
    fixture: dict,
    home_recent: Any,
    away_recent: Any,
    home_stats_rows: Any,
    away_stats_rows: Any,
    h2h_rows: Any,
    kickoff_at: str,
):
    """Builds 1X2 and goal markets from season venue splits + recent form; strict pre-kickoff cutoff."""
    kickoff = _date(kickoff_at)
    if kickoff is None:
        return {"available": False, "model_version": MODEL_VERSION, "reason": "Fecha de inicio no válida."}
    home = fixture.get("homeTeam") or {}
    away = fixture.get("awayTeam") or {}
    home_id, away_id = home.get("id"), away.get("id")
    league_id = (fixture.get("league") or {}).get("id")
    if not isinstance(home_id, int) or not isinstance(away_id, int) or not isinstance(league_id, int):
        return {"available": False, "model_version": MODEL_VERSION, "reason": "Highlightly no devolvió IDs válidos de equipos y competición."}
    hs = _league_row(home_stats_rows, league_id)
    aws = _league_row(away_stats_rows, league_id)
    if not hs or not aws:
        return {"available": False, "model_version": MODEL_VERSION, "reason": "No hay estadísticas de temporada coincidentes para ambos equipos en esta competición."}
    home_for = _rate(hs, "home", "scored")
    home_against = _rate(hs, "home", "received")
    away_for = _rate(aws, "away", "scored")
    away_against = _rate(aws, "away", "received")
    hr = _recent_rates(home_recent, home_id)
    ar = _recent_rates(away_recent, away_id)
    if None in (home_for, home_against, away_for, away_against) or not hr or not ar:
        return {"available": False, "model_version": MODEL_VERSION, "reason": "Muestra insuficiente o incompleta en estadísticas de temporada y últimos cinco partidos."}
    # Venue-specific season rates receive more weight; recent form is a modest adjustment.
    lam_home = 0.75 * math.sqrt(max(.05, home_for) * max(.05, away_against)) + 0.25 * (0.65 * hr["goals_for"] + 0.35 * ar["goals_against"])
    lam_away = 0.75 * math.sqrt(max(.05, away_for) * max(.05, home_against)) + 0.25 * (0.65 * ar["goals_for"] + 0.35 * hr["goals_against"])
    lam_home = max(.15, min(4.5, lam_home))
    lam_away = max(.15, min(4.5, lam_away))
    hp = [_poisson(lam_home, g) for g in range(11)]
    ap = [_poisson(lam_away, g) for g in range(11)]
    matrix = [[hp[h] * ap[a] for a in range(11)] for h in range(11)]
    total = sum(map(sum, matrix))
    matrix = [[p / total for p in row] for row in matrix]
    p_home = sum(matrix[h][a] for h in range(11) for a in range(11) if h > a)
    p_draw = sum(matrix[g][g] for g in range(11))
    p_away = sum(matrix[h][a] for h in range(11) for a in range(11) if h < a)
    btts = sum(matrix[h][a] for h in range(1, 11) for a in range(1, 11))
    markets = {}
    for line in (1.5, 2.5, 3.5):
        over = sum(matrix[h][a] for h in range(11) for a in range(11) if h + a > line)
        key = str(line).replace(".", "_")
        markets["over_" + key] = round(over, 6)
        markets["under_" + key] = round(1 - over, 6)
    scores = sorted(((matrix[h][a], h, a) for h in range(11) for a in range(11)), reverse=True)[:5]
    h2h_valid = []
    for item in h2h_rows if isinstance(h2h_rows, list) else []:
        dt = _date(item.get("date"))
        score = _score(((item.get("state") or {}).get("score") or {}).get("current"))
        if dt and dt < kickoff and score and str((item.get("state") or {}).get("description", "")).casefold().startswith("finished"):
            h2h_valid.append(item)
    return {
        "available": True, "model_version": MODEL_VERSION, "status": "SHADOW_ONLY_NOT_CALIBRATED",
        "probabilities": {"home": round(p_home, 6), "draw": round(p_draw, 6), "away": round(p_away, 6)},
        "expected_goals": {"home": round(lam_home, 3), "away": round(lam_away, 3), "total": round(lam_home + lam_away, 3)},
        "goal_markets": {"both_teams_to_score": {"yes": round(btts, 6), "no": round(1 - btts, 6)}, "total_goals": markets},
        "most_likely_scorelines": [{"home": h, "away": a, "probability": round(p, 6)} for p, h, a in scores],
        "highlightly_features": {
            "season_home_goals_for_per_game": round(home_for, 3),
            "season_home_goals_against_per_game": round(home_against, 3),
            "season_away_goals_for_per_game": round(away_for, 3),
            "season_away_goals_against_per_game": round(away_against, 3),
            "home_recent_form": hr, "away_recent_form": ar,
            "h2h_available_before_kickoff": len(h2h_valid),
            "league": (fixture.get("league") or {}).get("name"),
            "season": (fixture.get("league") or {}).get("season"),
        },
        "calibration": {"status": "not_calibrated", "note": "Candidato experimental; requiere backtest walk-forward por competición."},
        "recommendation": {"status": "NO_PLAY_UNTIL_VALIDATED", "reason": "No sustituye al modelo oficial hasta demostrar mejora estadística."},
    }
