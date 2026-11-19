"""Read-only adapter for public NHL web feeds.

The NHL's public web endpoints are undocumented. Keep their schema handling
isolated here, validate payloads defensively, and never persist or score data
from this adapter until source terms and coverage are reviewed.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any

import requests

BASE_URL = "https://api-web.nhle.com/v1"
HEADERS = {
    "User-Agent": "Sports-Predictor-NHL/0.1.0",
    "Accept": "application/json",
}
TIMEOUT_SECONDS = 20
FINAL_STATES = {"OFF", "FINAL"}


class NHLDataError(RuntimeError):
    """Raised when the public NHL feed is unavailable or malformed."""


def _localized(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("default") or next(iter(value.values()), None)
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _integer(value: Any) -> int | None:
    parsed = _number(value)
    return int(parsed) if parsed is not None and parsed.is_integer() else None


def _team(team: dict[str, Any] | None) -> dict[str, Any]:
    team = team if isinstance(team, dict) else {}
    return {
        "id": _integer(team.get("id")),
        "abbreviation": _localized(team.get("abbrev") or team.get("abbreviation")),
        "name": _localized(team.get("commonName")) or _localized(team.get("name")),
        "place_name": _localized(team.get("placeName")),
        "score": _integer(team.get("score")),
        "sog": _integer(team.get("sog")),
    }


def normalize_game(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one scoreboard row without guessing missing identity or scores."""
    if not isinstance(row, dict):
        return None
    game_id = _integer(row.get("id"))
    game_date = str(row.get("gameDate") or "").strip()
    if game_id is None or not re.fullmatch(r"\d{8,12}", str(game_id)):
        return None
    try:
        date.fromisoformat(game_date)
    except ValueError:
        return None

    state = str(row.get("gameState") or row.get("gameScheduleState") or "UNKNOWN").upper()
    period = row.get("periodDescriptor") or {}
    venue = row.get("venue") or {}
    return {
        "game_id": str(game_id),
        "game_date": game_date,
        "start_time_utc": row.get("startTimeUTC"),
        "game_state": state,
        "completed": state in FINAL_STATES,
        "game_type": _integer(row.get("gameType")),
        "period": _integer(period.get("number")) if isinstance(period, dict) else None,
        "period_type": _localized(period.get("periodType")) if isinstance(period, dict) else None,
        "venue": _localized(venue.get("default") if isinstance(venue, dict) else venue),
        "home": _team(row.get("homeTeam")),
        "away": _team(row.get("awayTeam")),
    }


def get_games(game_date: str | date | None = None) -> list[dict[str, Any]]:
    """Fetch the NHL scoreboard for one calendar date (UTC date semantics)."""
    if game_date is None:
        selected_date = datetime.now(timezone.utc).date()
    elif isinstance(game_date, datetime):
        selected_date = game_date.date()
    elif isinstance(game_date, date):
        selected_date = game_date
    else:
        try:
            selected_date = date.fromisoformat(str(game_date))
        except (TypeError, ValueError) as exc:
            raise ValueError("date debe usar el formato YYYY-MM-DD.") from exc

    try:
        response = requests.get(
            f"{BASE_URL}/score/{selected_date.isoformat()}",
            headers=HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise NHLDataError("No fue posible consultar el marcador público de NHL.") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
        raise NHLDataError("La respuesta del marcador NHL no contiene una lista de partidos.")
    return [
        normalized
        for row in payload["games"]
        if (normalized := normalize_game(row)) is not None
    ]



def get_team_season_schedule(team: str, season: str | int) -> dict[str, Any]:
    """Fetch one team's season schedule for historical coverage discovery.

    This is intentionally read-only: it does not persist results or feed a
    prediction model. The upstream NHL web endpoint is undocumented.
    """
    selected_team = str(team or "").strip().upper()
    selected_season = str(season or "").strip()
    if not re.fullmatch(r"[A-Z0-9]{2,4}", selected_team):
        raise ValueError("team NHL debe ser una abreviatura de 2 a 4 caracteres.")
    match = re.fullmatch(r"(\\d{4})(\\d{4})", selected_season)
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise ValueError("season debe usar el formato YYYY YYYY de temporadas consecutivas, por ejemplo 20252026.")

    try:
        response = requests.get(
            f"{BASE_URL}/club-schedule-season/{selected_team}/{selected_season}",
            headers=HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise NHLDataError("No fue posible consultar el calendario histórico público de NHL.") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
        raise NHLDataError("La respuesta del calendario NHL no contiene una lista de partidos.")

    games = [
        normalized
        for row in payload["games"]
        if (normalized := normalize_game(row)) is not None
    ]
    games.sort(key=lambda game: (game["game_date"], game["game_id"]))
    return {
        "success": True,
        "team": selected_team,
        "season": selected_season,
        "source": "NHL public club season schedule",
        "total": len(games),
        "games": games,
    }

def _player_name(value: Any) -> str | None:
    return _localized(value)


def _normalize_skater(row: dict[str, Any]) -> dict[str, Any]:
    name = _player_name(row.get("name"))
    return {
        "player_id": _integer(row.get("playerId")),
        "name": name,
        "position": _localized(row.get("position")),
        "goals": _integer(row.get("goals")),
        "assists": _integer(row.get("assists")),
        "points": _integer(row.get("points")),
        "shots": _integer(row.get("sog", row.get("shots"))),
        "hits": _integer(row.get("hits")),
        "blocked_shots": _integer(row.get("blockedShots")),
        "plus_minus": row.get("plusMinus") if isinstance(row.get("plusMinus"), int) else None,
        "penalty_minutes": _integer(row.get("pim")),
        "time_on_ice": _localized(row.get("toi")),
    }


def _normalize_goalie(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": _integer(row.get("playerId")),
        "name": _player_name(row.get("name")),
        "decision": _localized(row.get("decision")),
        "saves": _integer(row.get("saves")),
        "shots_against": _integer(row.get("shotsAgainst")),
        "save_percentage": _number(row.get("savePctg")),
        "goals_against": _integer(row.get("goalsAgainst")),
        "time_on_ice": _localized(row.get("toi")),
    }


def normalize_boxscore(payload: dict[str, Any], game_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise NHLDataError("La respuesta boxscore NHL no es un objeto válido.")

    # NHL may omit playerByGameStats entirely until a game has started.
    # Treat that as an unavailable-yet state, not as a malformed response.
    source = payload.get("playerByGameStats")
    if not isinstance(source, dict):
        if not payload.get("gameState") and not payload.get("id"):
            raise NHLDataError("La respuesta boxscore NHL no contiene identidad ni estado del partido.")
        return {
            "success": True,
            "game_id": str(game_id),
            "source": "NHL public GameCenter feed",
            "game_state": str(payload.get("gameState") or "UNKNOWN").upper(),
            "limited_scoring": bool(payload.get("limitedScoring", False)),
            "stats_available": False,
            "teams": {
                "home": {"skaters": [], "goalies": []},
                "away": {"skaters": [], "goalies": []},
            },
        }

    teams = {}
    for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
        group = source.get(key) or {}
        if not isinstance(group, dict):
            group = {}
        skaters = []
        for position_group in ("forwards", "defense"):
            values = group.get(position_group) or []
            if isinstance(values, list):
                skaters.extend(_normalize_skater(item) for item in values if isinstance(item, dict))
        goalies = group.get("goalies") or []
        teams[side] = {
            "skaters": skaters,
            "goalies": [
                _normalize_goalie(item) for item in goalies if isinstance(item, dict)
            ] if isinstance(goalies, list) else [],
        }
    stats_available = any(
        team["skaters"] or team["goalies"] for team in teams.values()
    )
    return {
        "success": True,
        "game_id": str(game_id),
        "source": "NHL public GameCenter feed",
        "game_state": str(payload.get("gameState") or "UNKNOWN").upper(),
        "limited_scoring": bool(payload.get("limitedScoring", False)),
        "stats_available": stats_available,
        "teams": teams,
    }


def get_boxscore(game_id: str) -> dict[str, Any]:
    selected_id = str(game_id or "").strip()
    if not re.fullmatch(r"\d{8,12}", selected_id):
        raise ValueError("game_id NHL debe contener entre 8 y 12 dígitos.")
    try:
        response = requests.get(
            f"{BASE_URL}/gamecenter/{selected_id}/boxscore",
            headers=HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise NHLDataError("No fue posible consultar el boxscore público de NHL.") from exc
    return normalize_boxscore(payload, selected_id)
