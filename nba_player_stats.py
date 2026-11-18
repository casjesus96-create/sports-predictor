"""Read-only NBA player boxscore parsing from ESPN's public summary endpoint."""
from __future__ import annotations

import copy
import math
import threading
import time

import requests

ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
TIMEOUT = 15
PLAYER_BOXSCORE_CACHE_TTL_SECONDS = 6 * 60 * 60
PLAYER_BOXSCORE_CACHE_MAX_ENTRIES = 512
_PLAYER_BOXSCORE_CACHE = {}
_PLAYER_BOXSCORE_CACHE_LOCK = threading.Lock()


PLAYER_STAT_ALIASES = {
    "points": {"pts", "points"},
    "assists": {"ast", "assists"},
    "rebounds": {"reb", "rebounds", "total rebounds"},
    "blocks": {"blk", "blocks"},
    "steals": {"stl", "steals"},
}


def _as_number(value):
    try:
        number = float(str(value).replace(",", "").strip())
        # Boxscore statistics and period scores cannot be negative or non-finite.
        if not math.isfinite(number) or number < 0:
            return None
        if number.is_integer():
            return int(number)
        return number
    except (TypeError, ValueError, OverflowError):
        return None


def _stat_value(names, values, aliases):
    for index, name in enumerate(names):
        normalized = str(name or "").strip().lower()
        if normalized in aliases and index < len(values):
            return _as_number(values[index])
    return None



def fetch_player_boxscore(game_id: str) -> dict:
    """Fetch a final historical boxscore, reusing successful results briefly across analyses."""
    normalized_id = str(game_id).strip()
    if not normalized_id.isdigit():
        raise ValueError("game_id NBA debe ser numérico.")

    now = time.monotonic()
    with _PLAYER_BOXSCORE_CACHE_LOCK:
        cached = _PLAYER_BOXSCORE_CACHE.get(normalized_id)
        if cached:
            expires_at, report = cached
            if expires_at > now:
                return copy.deepcopy(report)
            _PLAYER_BOXSCORE_CACHE.pop(normalized_id, None)

    response = requests.get(
        ESPN_SUMMARY_URL,
        params={"event": normalized_id},
        timeout=TIMEOUT,
        headers={"User-Agent": "Sports-Predictor-NBA/1.0.0", "Accept": "application/json"},
    )
    response.raise_for_status()
    report = parse_player_boxscore(response.json(), normalized_id)

    # Cache only usable boxscores. Missing/incomplete provider responses are retried
    # on the next analysis rather than being frozen as empty historical observations.
    if report.get("available"):
        with _PLAYER_BOXSCORE_CACHE_LOCK:
            expired = [
                key for key, (expires_at, _) in _PLAYER_BOXSCORE_CACHE.items()
                if expires_at <= now
            ]
            for key in expired:
                _PLAYER_BOXSCORE_CACHE.pop(key, None)
            while len(_PLAYER_BOXSCORE_CACHE) >= PLAYER_BOXSCORE_CACHE_MAX_ENTRIES:
                oldest_key = next(iter(_PLAYER_BOXSCORE_CACHE))
                _PLAYER_BOXSCORE_CACHE.pop(oldest_key, None)
            _PLAYER_BOXSCORE_CACHE[normalized_id] = (
                now + PLAYER_BOXSCORE_CACHE_TTL_SECONDS,
                copy.deepcopy(report),
            )
    return report


def _parse_period_scores(payload: dict) -> dict:
    """Extract actual quarter/overtime scores from ESPN competition linescores."""
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    competition = competitions[0] if competitions else {}
    competitors = competition.get("competitors") or []
    home = next((item for item in competitors if item.get("homeAway") == "home"), {})
    away = next((item for item in competitors if item.get("homeAway") == "away"), {})

    def periods(competitor):
        result = {}
        for index, line in enumerate(competitor.get("linescores") or [], start=1):
            raw_period = line.get("period", index)
            try:
                period = int(raw_period)
            except (TypeError, ValueError):
                period = index
            score = _as_number(line.get("displayValue", line.get("value")))
            if score is not None and period > 0:
                result[period] = score
        return result

    home_periods = periods(home)
    away_periods = periods(away)
    all_periods = sorted(set(home_periods) | set(away_periods))
    scores = []
    for period in all_periods:
        scores.append({
            "period": period,
            "label": f"Q{period}" if period <= 4 else f"OT{period - 4}",
            "away_points": away_periods.get(period),
            "home_points": home_periods.get(period),
        })
    return {
        "available": bool(scores),
        "periods": scores,
        "away_total": _as_number(away.get("score")),
        "home_total": _as_number(home.get("score")),
    }


def parse_player_boxscore(payload: dict, game_id: str) -> dict:
    """Normalize ESPN summary player stats and actual quarter scores without inventing values."""
    boxscore = payload.get("boxscore") or {}
    quarter_scores = _parse_period_scores(payload)
    teams = []
    for team_group in boxscore.get("players") or []:
        team = team_group.get("team") or {}
        team_name = team.get("displayName") or team.get("name") or "Equipo"
        players = []
        for stat_group in team_group.get("statistics") or []:
            names = stat_group.get("names") or stat_group.get("labels") or []
            for athlete_row in stat_group.get("athletes") or []:
                athlete = athlete_row.get("athlete") or {}
                values = athlete_row.get("stats") or []
                if athlete_row.get("didNotPlay") or athlete_row.get("played") is False:
                    continue
                stats = {
                    key: _stat_value(names, values, aliases)
                    for key, aliases in PLAYER_STAT_ALIASES.items()
                }
                # ESPN may return several statistical groups. Keep only actual player rows.
                if not athlete.get("id") and not athlete.get("displayName"):
                    continue
                players.append({
                    "player_id": str(athlete.get("id") or ""),
                    "name": athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or "Jugador",
                    "position": (athlete.get("position") or {}).get("abbreviation") or (athlete.get("position") or {}).get("name"),
                    "starter": bool(athlete_row.get("starter", False)),
                    **stats,
                })
        # One team can have multiple stat groups; collapse duplicate athlete rows.
        unique = {}
        conflicted_stats = {}
        for player in players:
            key = player["player_id"] or player["name"]
            existing = unique.setdefault(key, dict(player))
            player_conflicts = conflicted_stats.setdefault(key, set())
            for stat in PLAYER_STAT_ALIASES:
                if stat in player_conflicts:
                    continue
                existing_value = existing.get(stat)
                incoming_value = player.get(stat)
                if existing_value is None and incoming_value is not None:
                    existing[stat] = incoming_value
                elif incoming_value is not None and existing_value is not None and incoming_value != existing_value:
                    # Multiple ESPN stat groups disagree: keep the player, but do not
                    # select an arbitrary value for this statistic.
                    existing[stat] = None
                    player_conflicts.add(stat)
        if unique:
            normalized_players = []
            for player_key, player in unique.items():
                player["stat_conflicts"] = sorted(conflicted_stats.get(player_key, set()))
                normalized_players.append(player)
            teams.append({
                "team_id": str(team.get("id") or ""),
                "team": team_name,
                "abbreviation": team.get("abbreviation"),
                "players": sorted(normalized_players, key=lambda player: (not player["starter"], player["name"].casefold())),
            })
    return {
        "success": True,
        "sport": "NBA",
        "game_id": str(game_id),
        "source": "ESPN public summary boxscore",
        "quarter_scores": quarter_scores,
        "teams": teams,
        "player_count": sum(len(team["players"]) for team in teams),
        "available": bool(teams),
    }
