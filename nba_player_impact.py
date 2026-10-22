"""Shadow evaluation of individual NBA player projections; never changes official odds."""
from math import isfinite

PLAYER_STATS = {
    "points": "projected_points",
    "assists": "projected_assists",
    "rebounds": "projected_rebounds",
    "blocks": "projected_blocks",
    "steals": "projected_steals",
}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def evaluate_player_impact(player_projections, home_team_id, away_team_id):
    """Summarize individual production signals for research, not probability adjustment."""
    source = player_projections if isinstance(player_projections, dict) else {}
    if not source.get("available"):
        return {
            "available": False, "mode": "shadow_evaluation",
            "official_probability_changed": False,
            "reason": "player_projections_unavailable", "teams": {},
            "differences_home_minus_away": {},
            "note": "Sin datos individuales suficientes; no se aplica ajuste.",
        }
    summaries = {}
    for team in source.get("teams") or []:
        team_id = str(team.get("team_id") or "")
        if team_id not in {str(home_team_id), str(away_team_id)}:
            continue
        players = team.get("players") or []
        totals, coverage = {}, {}
        for stat, field in PLAYER_STATS.items():
            values = [_number(player.get(field)) for player in players]
            valid = [value for value in values if value is not None]
            totals[stat] = round(sum(valid), 2) if valid else None
            coverage[stat] = len(valid)
        summaries[team_id] = {
            "team": team.get("team") or "Equipo",
            "players_with_projections": len(players),
            "statistical_coverage": coverage,
            "player_appearance_coverage": {stat: sum(int(player.get("games_sampled_by_stat", {}).get(stat, 0) or 0) for player in players) for stat in PLAYER_STATS},
            "projected_team_totals": totals,
        }
    home_id, away_id = str(home_team_id), str(away_team_id)
    home, away = summaries.get(home_id), summaries.get(away_id)
    differences = {}
    for stat in PLAYER_STATS:
        hv = home["projected_team_totals"][stat] if home else None
        av = away["projected_team_totals"][stat] if away else None
        differences[stat] = round(hv - av, 2) if hv is not None and av is not None else None
    ready = bool(home and away and any(v is not None for v in differences.values()))
    return {
        "available": ready, "mode": "shadow_evaluation",
        "official_probability_changed": False,
        "method": "Suma descriptiva de promedios individuales disponibles; no ajusta por minutos, lesiones, rol, ritmo ni solapamiento entre estadísticas.",
        "teams": {"home": home, "away": away},
        "differences_home_minus_away": differences,
        "reason": None if ready else "insufficient_team_coverage",
        "note": "Señales experimentales; no son puntos porcentuales ni probabilidad de victoria.",
    }
