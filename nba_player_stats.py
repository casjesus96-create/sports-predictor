"""Read-only NBA player boxscore parsing from ESPN's public summary endpoint."""
from __future__ import annotations

import re
import requests

ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
TIMEOUT = 15

PLAYER_STAT_ALIASES = {
    "points": {"pts", "point", "points"},
    "assists": {"ast", "assist", "assists"},
    "rebounds": {"reb", "rebound", "rebounds", "total rebounds"},
    "blocks": {"blk", "block", "blocks"},
    "steals": {"stl", "steal", "steals"},
}


def _normalize_label(value):
    return re.sub(r"[^a-z0-9+]", "", str(value or "").strip().lower())


def _as_number(value):
    try:
        number = float(str(value).replace(",", "").strip())
        if number.is_integer():
            return int(number)
        return number
    except (TypeError, ValueError):
        return None


def _stat_value(names, values, aliases):
    normalized_aliases = {_normalize_label(alias) for alias in aliases}
    for index, name in enumerate(names):
        if _normalize_label(name) in normalized_aliases and index < len(values):
            return _as_number(values[index])
    return None


def _made_shots(value):
    """Read the made portion of ESPN strings such as '9-20'."""
    if value is None:
        return None
    match = re.match(r"^\s*(\d+)\s*(?:-|/)\s*\d+\s*$", str(value))
    return int(match.group(1)) if match else _as_number(value)


def _points_from_shooting(names, values):
    """Derive points only when all three made-shot counts are explicitly available."""
    normalized = [_normalize_label(name) for name in names]
    makes = {}
    aliases_by_key = {
        "fg": {"fg", "fieldgoals"},
        "3pt": {"3pt", "3p", "3ptfg", "3pm", "3pointers"},
        "ft": {"ft", "freethrows"},
    }
    for key, aliases in aliases_by_key.items():
        for index, label in enumerate(normalized):
            if label in aliases and index < len(values):
                makes[key] = _made_shots(values[index])
                break
    if all(makes.get(key) is not None for key in ("fg", "3pt", "ft")):
        # FG made includes three-pointers: add one extra point per made 3PT.
        return 2 * makes["fg"] + makes["3pt"] + makes["ft"]
    return None


def fetch_player_boxscore(game_id: str) -> dict:
    """Fetch one game's current boxscore from ESPN; never writes to prediction history."""
    normalized_id = str(game_id).strip()
    if not normalized_id.isdigit():
        raise ValueError("game_id NBA debe ser numérico.")
    response = requests.get(
        ESPN_SUMMARY_URL,
        params={"event": normalized_id},
        timeout=TIMEOUT,
        headers={"User-Agent": "Sports-Predictor-NBA/1.0.0", "Accept": "application/json"},
    )
    response.raise_for_status()
    return parse_player_boxscore(response.json(), normalized_id)


def parse_player_boxscore(payload: dict, game_id: str) -> dict:
    """Normalize ESPN summary boxscore player stats without inventing missing values."""
    boxscore = payload.get("boxscore") or {}
    teams = []
    for team_group in boxscore.get("players") or []:
        team = team_group.get("team") or {}
        team_name = team.get("displayName") or team.get("name") or "Equipo"
        players = []
        for stat_group in team_group.get("statistics") or []:
            names = stat_group.get("names") or stat_group.get("labels") or stat_group.get("keys") or []
            for athlete_row in stat_group.get("athletes") or []:
                athlete = athlete_row.get("athlete") or {}
                values = athlete_row.get("stats") or []
                if athlete_row.get("didNotPlay") or athlete_row.get("played") is False:
                    continue
                stats = {
                    key: _stat_value(names, values, aliases)
                    for key, aliases in PLAYER_STAT_ALIASES.items()
                }
                if stats["points"] is None:
                    stats["points"] = _points_from_shooting(names, values)
                if not athlete.get("id") and not athlete.get("displayName") and not athlete.get("fullName"):
                    continue
                position = athlete.get("position") or {}
                players.append({
                    "player_id": str(athlete.get("id") or ""),
                    "name": athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or "Jugador",
                    "position": (position.get("abbreviation") or position.get("name")) if isinstance(position, dict) else None,
                    "starter": bool(athlete_row.get("starter", False)),
                    **stats,
                })
        unique = {}
        for player in players:
            key = player["player_id"] or player["name"]
            existing = unique.setdefault(key, dict(player))
            for stat in PLAYER_STAT_ALIASES:
                if existing.get(stat) is None and player.get(stat) is not None:
                    existing[stat] = player[stat]
        if unique:
            teams.append({
                "team_id": str(team.get("id") or ""),
                "team": team_name,
                "abbreviation": team.get("abbreviation"),
                "players": sorted(unique.values(), key=lambda player: (not player["starter"], player["name"].casefold())),
            })
    return {
        "success": True,
        "sport": "NBA",
        "game_id": str(game_id),
        "source": "ESPN public summary boxscore",
        "teams": teams,
        "player_count": sum(len(team["players"]) for team in teams),
        "available": bool(teams),
    }
