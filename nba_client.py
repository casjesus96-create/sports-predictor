"""Cliente NBA basado en endpoints públicos de ESPN; no requiere API key.

ESPN acepta fechas de scoreboard por día o mes; para evitar los rangos
YYYYMMDD-YYYYMMDD (que pueden devolver HTTP 400), las consultas históricas
se hacen por mes y se filtran localmente al intervalo solicitado.
"""
from datetime import datetime, timedelta, timezone
import logging

import requests

logger = logging.getLogger(__name__)
UTC = timezone.utc
BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
HEADERS = {"User-Agent": "Sports-Predictor-NBA/1.0.0", "Accept": "application/json"}
TIMEOUT = 15


def _parse_dt(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _score(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_event(event):
    competitions = event.get("competitions") or []
    competition = competitions[0] if competitions else {}
    competitors = competition.get("competitors") or []
    home = next((x for x in competitors if x.get("homeAway") == "home"), {})
    away = next((x for x in competitors if x.get("homeAway") == "away"), {})
    status_obj = (event.get("status") or {}).get("type") or {}
    home_team = home.get("team") or {}
    away_team = away.get("team") or {}
    kickoff = _parse_dt(event.get("date") or competition.get("date"))
    return {
        "game_id": str(event.get("id") or ""),
        "league": "NBA",
        "season": (event.get("season") or {}).get("year"),
        "name": event.get("name"),
        "short_name": event.get("shortName"),
        "kickoff": kickoff.isoformat() if kickoff else None,
        "status": status_obj.get("state") or "unknown",
        "status_detail": status_obj.get("description") or status_obj.get("detail"),
        "completed": bool(status_obj.get("completed")),
        "home": home_team.get("displayName") or home_team.get("name"),
        "home_abbreviation": home_team.get("abbreviation"),
        "home_team_id": str(home_team.get("id") or ""),
        "away": away_team.get("displayName") or away_team.get("name"),
        "away_abbreviation": away_team.get("abbreviation"),
        "away_team_id": str(away_team.get("id") or ""),
        "home_score": _score(home.get("score")),
        "away_score": _score(away.get("score")),
        "venue": (competition.get("venue") or {}).get("fullName"),
        "neutral_site": bool(competition.get("neutralSite", False)),
    }


def _get_month_events(month_start):
    month_key = month_start.strftime("%Y%m")
    response = requests.get(
        f"{BASE_URL}/scoreboard",
        params={"dates": month_key, "limit": 1000},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    return [_normalize_event(x) for x in payload.get("events", [])]


def _iter_month_starts(start_date, end_date):
    current = start_date.replace(day=1)
    last = end_date.replace(day=1)
    while current <= last:
        yield current
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)


def _get_events(start_date, end_date):
    if end_date < start_date:
        return []
    events_by_id = {}
    for month_start in _iter_month_starts(start_date, end_date):
        for game in _get_month_events(month_start):
            game_id = game.get("game_id")
            kickoff = _parse_dt(game.get("kickoff"))
            if not game_id or kickoff is None:
                continue
            if start_date <= kickoff.date() <= end_date:
                events_by_id[game_id] = game
    return list(events_by_id.values())


def get_upcoming_games(days=21, limit=50):
    now = datetime.now(UTC)
    end_date = (now + timedelta(days=max(1, min(days, 45)))).date()
    events = _get_events(now.date(), end_date)
    games = [
        game for game in events
        if game.get("game_id") and game.get("kickoff")
        and _parse_dt(game["kickoff"]) > now
        and not game.get("completed")
    ]
    games.sort(key=lambda game: game["kickoff"])
    return games[:max(1, min(int(limit), 100))]


def get_game(game_id):
    if not str(game_id).strip().isdigit():
        return None
    response = requests.get(
        f"{BASE_URL}/summary",
        params={"event": str(game_id)},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]
    competitors = competition.get("competitors") or []
    home = next((x for x in competitors if x.get("homeAway") == "home"), {})
    away = next((x for x in competitors if x.get("homeAway") == "away"), {})
    status_obj = competition.get("status") or {}
    status_type = status_obj.get("type") or {}
    home_team = home.get("team") or {}
    away_team = away.get("team") or {}
    kickoff = _parse_dt(competition.get("date") or header.get("date"))
    return {
        "game_id": str(game_id), "league": "NBA",
        "kickoff": kickoff.isoformat() if kickoff else None,
        "status": status_type.get("state") or "unknown",
        "status_detail": status_type.get("description") or status_type.get("detail"),
        "completed": bool(status_type.get("completed")),
        "home": home_team.get("displayName") or home_team.get("name"),
        "home_abbreviation": home_team.get("abbreviation"),
        "home_team_id": str(home_team.get("id") or ""),
        "away": away_team.get("displayName") or away_team.get("name"),
        "away_abbreviation": away_team.get("abbreviation"),
        "away_team_id": str(away_team.get("id") or ""),
        "home_score": _score(home.get("score")),
        "away_score": _score(away.get("score")),
        "venue": (competition.get("venue") or {}).get("fullName"),
        "neutral_site": bool(competition.get("neutralSite", False)),
    }


def get_team_histories(team_ids, cutoff, days=180):
    """Obtiene historial de varios equipos en una sola pasada por meses."""
    cutoff_dt = _parse_dt(cutoff)
    normalized_ids = {str(team_id) for team_id in team_ids if team_id}
    result = {team_id: [] for team_id in normalized_ids}
    if not normalized_ids or cutoff_dt is None:
        return result

    start = (cutoff_dt - timedelta(days=max(30, min(days, 365)))).date()
    end = (cutoff_dt - timedelta(days=1)).date()
    if end < start:
        return result

    events = _get_events(start, end)
    for game in events:
        if not game.get("completed") or not game.get("kickoff"):
            continue
        kickoff = _parse_dt(game["kickoff"])
        if kickoff is None or kickoff >= cutoff_dt:
            continue
        if game.get("home_score") is None or game.get("away_score") is None:
            continue
        for team_id in normalized_ids.intersection({
            str(game.get("home_team_id") or ""),
            str(game.get("away_team_id") or ""),
        }):
            result[team_id].append(game)

    for team_id in result:
        result[team_id].sort(key=lambda item: item["kickoff"], reverse=True)
    return result


def get_team_history(team_id, cutoff, days=180):
    """Compatibilidad: historial de un equipo."""
    return get_team_histories([team_id], cutoff, days=days).get(str(team_id), [])
