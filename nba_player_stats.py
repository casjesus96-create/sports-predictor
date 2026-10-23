"""Read-only NBA player boxscore parsing from ESPN's public summary endpoint."""
from __future__ import annotations

import requests

ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
TIMEOUT = 15


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
        "quarter_scores": quarter_scores,
        "teams": teams,
        "player_count": sum(len(team["players"]) for team in teams),
        "available": bool(teams),
    }
