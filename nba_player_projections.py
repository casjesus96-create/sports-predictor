"""Pregame NBA player-stat projections from each player's recent completed games."""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import logging

from nba_player_stats import fetch_player_boxscore

logger = logging.getLogger(__name__)
STAT_KEYS = ("points", "assists", "rebounds", "blocks", "steals")
PROJECTION_KEYS = {
    "points": "projected_points",
    "assists": "projected_assists",
    "rebounds": "projected_rebounds",
    "blocks": "projected_blocks",
    "steals": "projected_steals",
}


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def aggregate_player_projections(game_reports, team_histories, max_games=5):
    """Aggregate per-appearance player averages from already completed game reports."""
    team_meta = {}
    for team_id, games in (team_histories or {}).items():
        for game in games or []:
            if str(game.get("home_team_id") or "") == str(team_id):
                team_meta[str(team_id)] = game.get("home") or game.get("home_abbreviation") or "Equipo"
                break
            if str(game.get("away_team_id") or "") == str(team_id):
                team_meta[str(team_id)] = game.get("away") or game.get("away_abbreviation") or "Equipo"
                break

    aggregates = defaultdict(lambda: defaultdict(lambda: {"name": "", "position": None, "games": set(), "totals": defaultdict(float), "counts": defaultdict(int), "stat_games": defaultdict(set)}))
    # Only project players belonging to the two teams whose histories were requested.
    # Historical boxscores also contain opponents; including them pollutes coverage.
    target_team_ids = {str(team_id) for team_id in (team_histories or {})}
    team_game_ids = defaultdict(set)

    for game_id, report in (game_reports or {}).items():
        if not report or not report.get("available"):
            continue
        for team in report.get("teams") or []:
            team_id = str(team.get("team_id") or "")
            if not team_id or (target_team_ids and team_id not in target_team_ids):
                continue
            team_game_ids[team_id].add(str(game_id))
            for player in team.get("players") or []:
                player_id = str(player.get("player_id") or player.get("name") or "").strip()
                if not player_id:
                    continue
                present_stats = [key for key in STAT_KEYS if isinstance(player.get(key), (int, float))]
                if not present_stats:
                    continue
                item = aggregates[team_id][player_id]
                item["name"] = player.get("name") or item["name"] or "Jugador"
                item["position"] = player.get("position") or item["position"]
                item["games"].add(str(game_id))
                for key in present_stats:
                    item["totals"][key] += float(player[key])
                    item["counts"][key] += 1
                    item["stat_games"][key].add(str(game_id))

    teams = []
    for team_id in sorted(set(team_meta) | set(aggregates)):
        players = []
        for player_id, item in aggregates.get(team_id, {}).items():
            row = {
                "player_id": player_id,
                "name": item["name"],
                "position": item["position"],
                "games_sampled": len(item["games"]),
                "games_sampled_by_stat": {key: len(item["stat_games"].get(key, set())) for key in STAT_KEYS},
            }
            for key, output_key in PROJECTION_KEYS.items():
                count = item["counts"].get(key, 0)
                row[output_key] = round(item["totals"][key] / count, 1) if count else None
            players.append(row)
        players.sort(key=lambda p: (-(p["projected_points"] if p["projected_points"] is not None else -1), p["name"].casefold()))
        if players:
            teams.append({
                "team_id": team_id,
                "team": team_meta.get(team_id, "Equipo"),
                "games_available": len(team_game_ids.get(team_id, set())),
                "statistical_coverage": {key: sum(1 for player in players if player.get(PROJECTION_KEYS[key]) is not None) for key in STAT_KEYS},
                "players": players,
            })
    return {
        "available": bool(teams and any(team["players"] for team in teams)),
        "method": "Promedio por aparición en los últimos partidos finalizados disponibles antes del inicio; no ajusta por lesiones, minutos ni quinteto confirmado.",
        "max_games_per_team": max_games,
        "teams": teams,
        "player_count": sum(len(team["players"]) for team in teams),
    }


def project_players_from_recent_games(team_histories, cutoff, max_games=5):
    """Fetch recent completed boxscores, strictly before cutoff, and average each player's stats."""
    cutoff_dt = _parse_datetime(cutoff)
    if cutoff_dt is None:
        return {
            "available": False, "method": "No hay una hora de corte válida.",
            "max_games_per_team": max_games, "teams": [], "player_count": 0,
        }

    selected = {}
    for games in (team_histories or {}).values():
        eligible = []
        for game in games or []:
            game_id = str(game.get("game_id") or "")
            kickoff = _parse_datetime(game.get("kickoff"))
            if game_id and kickoff and kickoff < cutoff_dt and game.get("completed", True):
                eligible.append(game)
        for game in eligible[:max_games]:
            selected[str(game["game_id"])] = game

    reports = {}
    if selected:
        with ThreadPoolExecutor(max_workers=min(5, len(selected))) as pool:
            futures = {pool.submit(fetch_player_boxscore, game_id): game_id for game_id in selected}
            for future in as_completed(futures):
                game_id = futures[future]
                try:
                    reports[game_id] = future.result()
                except Exception as exc:
                    logger.warning("No se pudo obtener boxscore individual NBA game_id=%s: %s", game_id, exc)
                    reports[game_id] = {"available": False, "teams": []}

    return aggregate_player_projections(reports, team_histories, max_games=max_games)
