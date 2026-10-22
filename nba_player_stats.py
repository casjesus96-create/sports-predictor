"""Read-only NBA player boxscore parsing from ESPN's public summary endpoint."""
from __future__ import annotations


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
        if number.is_integer():
            return int(number)
        return number
    except (TypeError, ValueError):
        return None


def _stat_value(names, values, aliases):
    for index, name in enumerate(names):
        normalized = str(name or "").strip().lower()
        if normalized in aliases and index < len(values):
            return _as_number(values[index])
    return None


def parse_player_boxscore(payload: dict, game_id: str) -> dict:
    """Normalize ESPN summary boxscore player stats without inventing missing values."""
    boxscore = payload.get("boxscore") or {}
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
