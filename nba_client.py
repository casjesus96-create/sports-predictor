"""Cliente NBA basado en endpoints públicos de ESPN; no requiere API key.

ESPN acepta fechas de scoreboard por día o mes; para evitar los rangos
YYYYMMDD-YYYYMMDD (que pueden devolver HTTP 400), las consultas históricas
se hacen por mes y se filtran localmente al intervalo solicitado.
"""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
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



BOX_SCORE_KEYS = {
    "points": ("points", "pts"),
    "rebounds": ("rebounds", "totalrebounds", "reb"),
    "offensive_rebounds": ("offensiverebounds", "oreb"),
    "defensive_rebounds": ("defensiverebounds", "dreb"),
    "assists": ("assists", "ast"),
    "steals": ("steals", "stl"),
    "blocks": ("blocks", "blk"),
    "turnovers": ("turnovers", "to"),
    "fouls": ("fouls", "personalfouls", "pf"),
    "field_goal_pct": ("fieldgoalpct", "fieldgoalpercentage", "fgpct"),
    "three_point_pct": ("threepointfieldgoalpct", "threepointpercentage", "3ppct", "threepointpct"),
    "free_throw_pct": ("freethrowpct", "freethrowpercentage", "ftpct"),
}


def _stat_number(value):
    if value is None:
        return None
    try:
        text = str(value).strip().replace("%", "")
        if "-" in text and not text.startswith("-"):
            made, attempted = text.split("-", 1)
            made_value, attempted_value = float(made), float(attempted)
            return round(made_value / attempted_value * 100, 2) if attempted_value else 0.0
        return float(text)
    except (TypeError, ValueError):
        return None


def _normalize_boxscore_stats(raw_stats):
    normalized = {}
    for stat in raw_stats or []:
        name = str(stat.get("name") or stat.get("abbreviation") or "").strip().lower()
        key = "".join(char for char in name if char.isalnum())
        value = _stat_number(stat.get("displayValue", stat.get("value")))
        if value is None:
            continue
        for target, aliases in BOX_SCORE_KEYS.items():
            alias_keys = {"".join(char for char in alias.lower() if char.isalnum()) for alias in aliases}
            if key in alias_keys:
                normalized[target] = value
                break

        # ESPN sometimes exposes makes-attempts rather than a percentage.
        # Check three-point attempts before general field-goal attempts because
        # the former key also contains the latter substring.
        if "threepointfieldgoalsmade" in key and "attempted" in key:
            normalized.setdefault("three_point_pct", value)
        elif "fieldgoalsmade" in key and "attempted" in key:
            normalized.setdefault("field_goal_pct", value)
        elif "freethrowsmade" in key and "attempted" in key:
            normalized.setdefault("free_throw_pct", value)
    return normalized


def _get_boxscore_for_game(game_id):
    response = requests.get(
        f"{BASE_URL}/summary",
        params={"event": str(game_id)},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    boxscore = payload.get("boxscore") or {}
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    competition = competitions[0] if competitions else {}
    period_scores = {}
    for competitor in competition.get("competitors") or []:
        team = competitor.get("team") or {}
        team_id = str(team.get("id") or "")
        if not team_id:
            continue
        period_scores[team_id] = [
            _score(line.get("displayValue", line.get("value")))
            for line in (competitor.get("linescores") or [])[:4]
        ]
    team_stats = {}
    for item in boxscore.get("teams") or []:
        team = item.get("team") or {}
        team_id = str(team.get("id") or item.get("id") or "")
        stats = _normalize_boxscore_stats(item.get("statistics") or [])
        if team_id:
            # Quarter scores live in header.competitions[].competitors[].linescores.
            # Preserve them even when ESPN omits team statistics in boxscore.teams.
            stats["_quarter_points"] = period_scores.get(team_id, [])
            team_stats[team_id] = stats
    # Some ESPN responses include period scores in the header but omit a team's
    # boxscore entry entirely. Keep a minimal entry so quarter auditing can still
    # use the official linescores without inventing points.
    for team_id, quarters in period_scores.items():
        if team_id not in team_stats:
            team_stats[team_id] = {"_quarter_points": quarters}
    return str(game_id), team_stats


def get_team_boxscore_histories(team_histories, max_games=5):
    """Obtiene estadísticas de equipo de los últimos partidos finalizados, sin consultar el partido objetivo."""
    selected = {}
    for team_id, games in (team_histories or {}).items():
        for game in (games or [])[:max_games]:
            game_id = str(game.get("game_id") or "")
            if game_id:
                selected[game_id] = game

    if not selected:
        return {str(team_id): [] for team_id in (team_histories or {})}

    stats_by_game = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_get_boxscore_for_game, game_id): game_id
            for game_id in selected
        }
        for future in as_completed(futures):
            game_id = futures[future]
            try:
                _, stats_by_game[game_id] = future.result()
            except Exception as exc:
                logger.warning("No se pudieron obtener estadísticas boxscore NBA game_id=%s: %s", game_id, exc)
                stats_by_game[game_id] = {}

    result = {str(team_id): [] for team_id in (team_histories or {})}
    for team_id, games in (team_histories or {}).items():
        team_key = str(team_id)
        for game in (games or [])[:max_games]:
            game_id = str(game.get("game_id") or "")
            game_stats = stats_by_game.get(game_id, {})
            own_stats = game_stats.get(team_key)
            opponent_id = str(
                game.get("away_team_id") if str(game.get("home_team_id")) == team_key
                else game.get("home_team_id") or ""
            )
            opponent_stats = game_stats.get(opponent_id)
            if own_stats:
                result.setdefault(team_key, []).append({
                    "game_id": game_id,
                    "kickoff": game.get("kickoff"),
                    "stats": own_stats,
                    "opponent_stats": opponent_stats or {},
                })
    return result

def get_team_history(team_id, cutoff, days=180):
    """Compatibilidad: historial de un equipo."""
    return get_team_histories([team_id], cutoff, days=days).get(str(team_id), [])
