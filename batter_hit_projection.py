"""Experimental pregame 1+ hit projections for confirmed MLB batting orders.

Probabilities are intentionally separate from the official MLB winner model.
They use the batter's current-season AVG and a transparent batting-order estimate
of at-bats; they are not calibrated betting probabilities.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import requests

from batter_pitcher_engine import _fetch_vs_pitcher_stats

MLB_API = "https://statsapi.mlb.com/api/v1"
TIMEOUT_SECONDS = 15
HEADERS = {"User-Agent": "Sports-Predictor/1.0", "Accept": "application/json"}

# Approximate expected at-bats by batting-order slot, not a guaranteed outcome.
EXPECTED_AT_BATS_BY_SLOT = {
    1: 4.35, 2: 4.25, 3: 4.15, 4: 4.05, 5: 3.95,
    6: 3.85, 7: 3.75, 8: 3.65, 9: 3.55,
}


def calculate_one_plus_hit_probability(batting_average, expected_at_bats):
    """Approximate P(1+ hit) as 1 - (1 - AVG) ** expected at-bats."""
    try:
        average = float(batting_average)
        opportunities = float(expected_at_bats)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(average) or not math.isfinite(opportunities):
        return None
    if not 0 <= average <= 1 or opportunities <= 0:
        return None
    return min(1.0, max(0.0, 1.0 - (1.0 - average) ** opportunities))


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _fetch_season_hitting_stats(player_ids, season):
    ids = sorted({int(value) for value in player_ids if _int(value)})
    if not ids:
        return {}
    response = requests.get(
        f"{MLB_API}/people",
        params={
            "personIds": ",".join(map(str, ids)),
            "hydrate": f"stats(group=[hitting],type=[season],season={int(season)})",
        },
        timeout=TIMEOUT_SECONDS,
        headers=HEADERS,
    )
    response.raise_for_status()
    result = {}
    for person in response.json().get("people") or []:
        player_id = _int(person.get("id"))
        if not player_id:
            continue
        for group in person.get("stats") or []:
            for split in group.get("splits") or []:
                stat = split.get("stat") or {}
                at_bats = _int(stat.get("atBats"))
                hits = _int(stat.get("hits"))
                average = _float(stat.get("avg"))
                if average is None and at_bats and hits is not None:
                    average = hits / at_bats
                if average is not None and at_bats is not None and at_bats > 0:
                    result[player_id] = {
                        "season": int(season),
                        "avg": average,
                        "at_bats": at_bats,
                        "hits": hits,
                    }
                    break
            if player_id in result:
                break
    return result


def build_batter_hit_projections(batter_pitcher_matchups, season=2026):
    """Project 1+ hit only for MLB-published confirmed lineups."""
    result = {
        "available": False,
        "status": "unavailable",
        "season": int(season),
        "method": "season_avg_times_expected_at_bats_v1",
        "lineup_requirement": "confirmed",
        "teams": [],
        "note": "Se requieren alineaciones confirmadas y estadísticas de bateo de la temporada.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if not isinstance(batter_pitcher_matchups, dict):
        return result

    confirmed_teams = []
    player_ids = []
    for side, team_key in (("home", "home_team"), ("away", "away_team")):
        team = batter_pitcher_matchups.get(team_key) or {}
        if not team.get("lineup_confirmed") or not isinstance(team.get("hitters"), list):
            continue
        lineup = []
        for hitter in team["hitters"]:
            if not isinstance(hitter, dict):
                continue
            player_id = _int(hitter.get("player_id"))
            name = str(hitter.get("player_name") or "").strip()
            if not player_id or not name:
                continue
            slot = _int(hitter.get("batting_order"))
            if not slot or slot not in EXPECTED_AT_BATS_BY_SLOT:
                continue
            normalized = {
                "player_id": player_id,
                "player_name": name,
                "batting_order": slot,
                "position": hitter.get("position"),
            }
            lineup.append(normalized)
            player_ids.append(player_id)
        if lineup:
            confirmed_teams.append({
                "side": side,
                "team_name": team.get("team_name") or batter_pitcher_matchups.get(side + "_team_name") or side,
                "lineup_source": team.get("lineup_source") or "MLB Stats API",
                "hitters": lineup,
            })

    if not confirmed_teams:
        result["note"] = "No hay alineación confirmada guardada. Vuelve a analizar cuando MLB publique el orden al bate."
        return result

    try:
        stats_by_player = _fetch_season_hitting_stats(player_ids, season)
    except (requests.RequestException, ValueError, TypeError) as exc:
        result["note"] = "No se pudieron recuperar estadísticas de temporada para los bateadores confirmados."
        result["error_type"] = type(exc).__name__
        return result

    projected_teams = []
    for team in confirmed_teams:
        hitters = []
        for hitter in team["hitters"]:
            stats = stats_by_player.get(hitter["player_id"])
            if not stats:
                continue
            expected_ab = EXPECTED_AT_BATS_BY_SLOT[hitter["batting_order"]]
            probability = calculate_one_plus_hit_probability(stats["avg"], expected_ab)
            if probability is None:
                continue
            hitters.append({
                **hitter,
                "season_avg": round(stats["avg"], 3),
                "season_hits": stats["hits"],
                "season_at_bats": stats["at_bats"],
                "expected_at_bats": expected_ab,
                "probability_1plus_hit": round(probability, 6),
                "probability_percent": round(probability * 100, 2),
                "status": "experimental",
            })
        projected_teams.append({
            "side": team["side"],
            "team_name": team["team_name"],
            "lineup_source": team["lineup_source"],
            "lineup_confirmed": True,
            "hitters": hitters,
        })

    count = sum(len(team["hitters"]) for team in projected_teams)
    result.update({
        "available": count > 0,
        "status": "experimental" if count else "unavailable",
        "teams": projected_teams,
        "note": (
            "Probabilidad experimental de 1+ hit: AVG de temporada y oportunidades estimadas según el turno al bate. "
            "No está calibrada históricamente y no sustituye al modelo oficial."
            if count else
            "La alineación está confirmada, pero no hay estadísticas de temporada utilizables para sus bateadores."
        ),
    })
    return result


def build_live_batter_hit_projections(live_teams, season=2026, current_inning=1, inning_state="Top", game_status="Warmup"):
    """Experimental P(1+ hit by game end), conditional on observed hits and game progress.

    For batters with a hit already, the event is already achieved (100%, not a forecast).
    For batters without a hit, estimate remaining AB opportunities from lineup slot and
    the fraction of game remaining, then apply season AVG. This is an uncalibrated
    approximation and must not be confused with a validated in-play betting model.
    """
    try:
        inning = max(1, int(current_inning or 1))
    except (TypeError, ValueError):
        inning = 1
    half = str(inning_state or "Top").lower()
    remaining_ninths = max(0.0, min(1.0, (10.0 - inning + (0.5 if half == "top" else 0.0)) / 9.0))
    status = str(game_status or "").lower()
    if status in {"final", "game over", "completed early"}:
        remaining_ninths = 0.0

    normalized_teams = []
    player_ids = []
    for team in live_teams if isinstance(live_teams, list) else []:
        if not isinstance(team, dict):
            continue
        hitters = []
        for hitter in team.get("hitters") or []:
            if not isinstance(hitter, dict):
                continue
            player_id = _int(hitter.get("player_id"))
            slot = _int(hitter.get("batting_order"))
            name = str(hitter.get("player_name") or "").strip()
            if not player_id or not name or not slot or slot not in EXPECTED_AT_BATS_BY_SLOT:
                continue
            hits = _int(hitter.get("hits_in_game"))
            at_bats = _int(hitter.get("at_bats_in_game"))
            normalized = {
                "player_id": player_id,
                "player_name": name,
                "batting_order": slot,
                "position": hitter.get("position"),
                "hits_in_game": max(0, hits or 0),
                "at_bats_in_game": max(0, at_bats or 0),
            }
            hitters.append(normalized)
            player_ids.append(player_id)
        if hitters:
            normalized_teams.append({
                "side": team.get("side"),
                "team_name": team.get("team_name") or team.get("side") or "Equipo",
                "opposing_pitcher_id": _int(team.get("opposing_pitcher_id")),
                "opposing_pitcher_name": team.get("opposing_pitcher_name"),
                "pitcher_source": team.get("pitcher_source"),
                "hitters": hitters,
            })

    result = {
        "available": False,
        "status": "unavailable",
        "season": int(season),
        "method": "live_remaining_opportunities_shrunk_batter_vs_pitcher_v2",
        "current_inning": inning,
        "inning_state": inning_state,
        "remaining_game_fraction": round(remaining_ninths, 3),
        "teams": [],
        "note": "Se requieren alineación publicada y estadísticas de bateo de temporada para estimar los hits restantes.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if not normalized_teams:
        return result
    try:
        stats_by_player = _fetch_season_hitting_stats(player_ids, season)
    except (requests.RequestException, ValueError, TypeError) as exc:
        result["note"] = "No se pudieron recuperar estadísticas de temporada para calcular la proyección en vivo."
        result["error_type"] = type(exc).__name__
        return result

    # Direct batter-vs-pitcher history is optional. Keep the season-AVG baseline
    # intact if the pitcher or reliable history is unavailable.
    pitcher_stats_by_team = {}
    for team in normalized_teams:
        pitcher_id = team.get("opposing_pitcher_id")
        if not pitcher_id:
            continue
        try:
            pitcher_stats_by_team[team["side"]] = _fetch_vs_pitcher_stats(
                [h["player_id"] for h in team["hitters"]], pitcher_id
            )
        except (requests.RequestException, ValueError, TypeError, KeyError):
            pitcher_stats_by_team[team["side"]] = {}

    projected_teams = []
    for team in normalized_teams:
        projected_hitters = []
        matchup_stats = pitcher_stats_by_team.get(team["side"], {})
        for hitter in team["hitters"]:
            stats = stats_by_player.get(hitter["player_id"])
            if not stats:
                projected_hitters.append({
                    **hitter,
                    "season_avg": None,
                    "expected_remaining_at_bats": None,
                    "probability_1plus_hit": None,
                    "probability_percent": None,
                    "status": "unavailable",
                    "projection_note": "Sin AVG de temporada utilizable para este bateador.",
                })
                continue
            vs_pitcher = matchup_stats.get(hitter["player_id"]) or {}
            vs_pitcher_ab = _int(vs_pitcher.get("at_bats")) or 0
            vs_pitcher_avg = _float(vs_pitcher.get("avg"))
            # Shrink direct matchup AVG toward season AVG; small samples get little weight.
            matchup_weight = vs_pitcher_ab / (vs_pitcher_ab + 50.0) if vs_pitcher_ab > 0 else 0.0
            adjusted_avg = stats["avg"]
            if vs_pitcher_avg is not None and vs_pitcher_ab > 0:
                adjusted_avg = (stats["avg"] * (1.0 - matchup_weight)) + (vs_pitcher_avg * matchup_weight)
                adjusted_avg = min(0.60, max(0.05, adjusted_avg))
            expected_remaining_ab = max(
                0.0,
                EXPECTED_AT_BATS_BY_SLOT[hitter["batting_order"]] * remaining_ninths,
            )
            # Treat the identified pitcher as relevant for at most the next plate
            # appearance. Later appearances use season AVG because the bullpen/
            # future pitcher is unknown; do not project the current pitcher across
            # every remaining at-bat.
            next_pa_ab = min(1.0, expected_remaining_ab)
            later_ab = max(0.0, expected_remaining_ab - next_pa_ab)
            probability_additional_hit = (
                1.0
                - ((1.0 - adjusted_avg) ** next_pa_ab)
                * ((1.0 - stats["avg"]) ** later_ab)
            ) if expected_remaining_ab > 0 else 0.0
            probability_additional_hit = min(1.0, max(0.0, probability_additional_hit))
            if hitter["hits_in_game"] > 0:
                probability = 1.0
                note = (
                    "Ya consiguió al menos un hit; el 1+ hit del partido está cumplido. "
                    "La probabilidad de otro hit es una estimación separada; el pitcher identificado "
                    "solo se aplica a la próxima aparición y las posteriores usan AVG de temporada."
                )
            else:
                probability = calculate_one_plus_hit_probability(adjusted_avg, expected_remaining_ab)
                note = (
                    "Estimación experimental: el pitcher identificado solo se aplica a la próxima "
                    "aparición; las oportunidades posteriores usan AVG de temporada."
                    if vs_pitcher_ab > 0 and vs_pitcher_avg is not None
                    else "Estimación experimental basada en AVG de temporada y oportunidades restantes; pitcher rival sin ajuste directo fiable."
                )
            projected_hitters.append({
                **hitter,
                "season_avg": round(stats["avg"], 3),
                "adjusted_avg": round(adjusted_avg, 3),
                "vs_pitcher_avg": round(vs_pitcher_avg, 3) if vs_pitcher_avg is not None and vs_pitcher_ab > 0 else None,
                "vs_pitcher_at_bats": vs_pitcher_ab,
                "opposing_pitcher_name": team.get("opposing_pitcher_name"),
                "pitcher_source": team.get("pitcher_source"),
                "matchup_weight": round(matchup_weight, 3),
                "season_hits": stats["hits"],
                "season_at_bats": stats["at_bats"],
                "expected_remaining_at_bats": round(expected_remaining_ab, 2),
                "probability_1plus_hit": round(probability, 6) if probability is not None else None,
                "probability_percent": round(probability * 100, 2) if probability is not None else None,
                "probability_additional_hit": round(probability_additional_hit, 6),
                "probability_additional_hit_percent": round(probability_additional_hit * 100, 2),
                "status": "experimental" if probability is not None else "unavailable",
                "projection_note": note,
            })
        projected_teams.append({
            "side": team["side"],
            "team_name": team["team_name"],
            "opposing_pitcher_name": team.get("opposing_pitcher_name"),
            "pitcher_source": team.get("pitcher_source"),
            "hitters": projected_hitters,
        })
    available_count = sum(
        1 for team in projected_teams for hitter in team["hitters"]
        if hitter.get("probability_percent") is not None
    )
    result.update({
        "available": available_count > 0,
        "status": "experimental" if available_count else "unavailable",
        "teams": projected_teams,
        "note": (
            "Proyección experimental condicional de 1+ hit hasta el final del partido. "
            "Usa AVG de temporada, oportunidades restantes aproximadas y, cuando existe historial, un ajuste conservador bateador-vs-pitcher; no está calibrada con backtesting "
            "y no sustituye al modelo oficial."
        ),
    })
    return result
