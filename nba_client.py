"""Cliente NBA basado en endpoints públicos de ESPN; no requiere API key."""
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


def _get_events(start_date, end_date):
    start = start_date.strftime("%Y%m%d")
    end = end_date.strftime("%Y%m%d")
    response = requests.get(
        f"{BASE_URL}/scoreboard",
        params={"dates": f"{start}-{end}", "limit": 1000},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    return [_normalize_event(x) for x in payload.get("events", [])]


def get_upcoming_games(days=21, limit=50):
    now = datetime.now(UTC)
    events = _get_events(now.date(), (now + timedelta(days=max(1, min(days, 45)))).date())
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
    events = header.get("competitions") or []
    event = None
    # Summary header typically exposes a competition but not the scoreboard event wrapper.
    if events:
        competition = events[0]
        competitors = competition.get("competitors") or []
        home = next((x for x in competitors if x.get("homeAway") == "home"), {})
        away = next((x for x in competitors if x.get("homeAway") == "away"), {})
        status_obj = competition.get("status") or {}
        status_type = status_obj.get("type") or {}
        home_team = home.get("team") or {}
        away_team = away.get("team") or {}
        kickoff = _parse_dt(competition.get("date") or header.get("date"))
        event = {
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
    return event


def get_team_history(team_id, cutoff, days=180):
    cutoff_dt = _parse_dt(cutoff)
    if not team_id or cutoff_dt is None:
        return []
    start = (cutoff_dt - timedelta(days=max(30, min(days, 365)))).date()
    end = (cutoff_dt - timedelta(days=1)).date()
    if end < start:
        return []
    events = _get_events(start, end)
    team_id = str(team_id)
    games = []
    for game in events:
        if not game.get("completed") or not game.get("kickoff"):
            continue
        if _parse_dt(game["kickoff"]) >= cutoff_dt:
            continue
        if team_id not in {game.get("home_team_id"), game.get("away_team_id")}:
            continue
        if game.get("home_score") is None or game.get("away_score") is None:
            continue
        games.append(game)
    return sorted(games, key=lambda item: item["kickoff"], reverse=True)
