"""Chronological, read-only audit of NFL pregame feature availability."""
import csv
import gzip
import io
from datetime import datetime, timezone

import requests

from nfl_client import load_schedule
from nfl_data_coverage import NFLVERSE_RELEASES

TIMEOUT_SECONDS = 25
TEAM_STATS_URL = (
    NFLVERSE_RELEASES
    + "/stats_team/stats_team_week_{season}.csv.gz"
)
PBP_URL = (
    NFLVERSE_RELEASES
    + "/pbp/play_by_play_{season}.csv.gz"
)


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _download_rows(session, url):
    response = session.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(response.content), mode="rb") as zipped:
        wrapper = io.TextIOWrapper(zipped, encoding="utf-8-sig", errors="replace")
        reader = csv.DictReader(wrapper)
        return list(reader), list(reader.fieldnames or [])


def _number(row, key):
    try:
        value = row.get(key)
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def audit_nfl_pregame_feature_coverage(season=2026, session=requests):
    """Measure whether candidate metrics exist strictly before each target kickoff."""
    games = load_schedule(season=season)
    schedule_by_id = {
        str(game.get("game_id")): game
        for game in games
        if game.get("game_id") and _parse_time(game.get("kickoff"))
    }
    completed = {}
    for game_id, game in schedule_by_id.items():
        kickoff = _parse_time(game.get("kickoff"))
        if (
            game.get("game_type") == "REG"
            and game.get("home_score") is not None
            and game.get("away_score") is not None
            and kickoff is not None
        ):
            completed[game_id] = game

    sources = []
    try:
        team_rows, team_columns = _download_rows(
            session, TEAM_STATS_URL.format(season=season)
        )
        sources.append({
            "key": "weekly_team_stats", "available": True,
            "rows": len(team_rows), "columns": len(team_columns), "error": None,
        })
    except (requests.RequestException, OSError, EOFError, csv.Error) as exc:
        team_rows, team_columns = [], []
        sources.append({
            "key": "weekly_team_stats", "available": False,
            "rows": 0, "columns": 0, "error": type(exc).__name__,
        })

    try:
        pbp_rows, pbp_columns = _download_rows(
            session, PBP_URL.format(season=season)
        )
        sources.append({
            "key": "play_by_play", "available": True,
            "rows": len(pbp_rows), "columns": len(pbp_columns), "error": None,
        })
    except (requests.RequestException, OSError, EOFError, csv.Error) as exc:
        pbp_rows, pbp_columns = [], []
        sources.append({
            "key": "play_by_play", "available": False,
            "rows": 0, "columns": 0, "error": type(exc).__name__,
        })

    team_history = {}
    for row in team_rows:
        game_id = str(row.get("game_id") or "")
        game = completed.get(game_id)
        if game is None:
            continue
        team = str(row.get("team") or "").strip().upper()
        if not team:
            continue
        team_history.setdefault(team, []).append({
            "kickoff": _parse_time(game.get("kickoff")),
            "game_id": game_id,
            "passing_epa": _number(row, "passing_epa"),
            "rushing_epa": _number(row, "rushing_epa"),
            "passing_interceptions": _number(row, "passing_interceptions"),
            "sacks_suffered": _number(row, "sacks_suffered"),
            "rushing_fumbles_lost": _number(row, "rushing_fumbles_lost"),
        })

    pbp_history = {}
    for row in pbp_rows:
        game_id = str(row.get("game_id") or "")
        game = completed.get(game_id)
        if game is None:
            continue
        kickoff = _parse_time(game.get("kickoff"))
        if kickoff is None:
            continue
        if _truthy(row.get("play_deleted")) or _truthy(row.get("aborted_play")):
            continue
        offense = str(row.get("posteam") or "").strip().upper()
        defense = str(row.get("defteam") or "").strip().upper()
        epa = _number(row, "epa")
        success = _number(row, "success")
        down = _number(row, "down")
        third_converted = _truthy(row.get("third_down_converted"))
        if offense:
            bucket = pbp_history.setdefault((offense, game_id), {
                "kickoff": kickoff, "epa_sum": 0.0, "epa_n": 0,
                "success_n": 0, "success_yes": 0,
                "third_n": 0, "third_yes": 0,
            })
            if epa is not None:
                bucket["epa_sum"] += epa
                bucket["epa_n"] += 1
            if success is not None:
                bucket["success_n"] += 1
                bucket["success_yes"] += int(success > 0)
            if down == 3:
                bucket["third_n"] += 1
                bucket["third_yes"] += int(third_converted)
        if defense and epa is not None:
            bucket = pbp_history.setdefault(("DEF:" + defense, game_id), {
                "kickoff": kickoff, "epa_sum": 0.0, "epa_n": 0,
                "success_n": 0, "success_yes": 0,
                "third_n": 0, "third_yes": 0,
            })
            bucket["epa_sum"] += epa
            bucket["epa_n"] += 1

    targets = [
        game for game in games
        if game.get("game_type") == "REG"
        and game.get("home") and game.get("away")
        and _parse_time(game.get("kickoff"))
    ]
    target_count = len(targets)
    history_thresholds = {1: 0, 3: 0, 5: 0}
    metric_counts = {
        "team_passing_epa": 0,
        "team_rushing_epa": 0,
        "team_turnover_data": 0,
        "pbp_offensive_epa": 0,
        "pbp_success_rate": 0,
        "pbp_third_down_rate": 0,
        "pbp_defensive_epa_allowed": 0,
    }
    for target in targets:
        cutoff = _parse_time(target["kickoff"])
        team_counts = {}
        for team in (target["home"], target["away"]):
            history = [
                item for item in team_history.get(str(team).upper(), [])
                if item["kickoff"] is not None and item["kickoff"] < cutoff
            ]
            # Distinct completed games only; no same-kickoff or future game.
            history = {item["game_id"]: item for item in history}
            team_counts[str(team).upper()] = list(history.values())
        for threshold in history_thresholds:
            if all(len(items) >= threshold for items in team_counts.values()):
                history_thresholds[threshold] += 1
        if all(any(item["passing_epa"] is not None for item in items)
               for items in team_counts.values()):
            metric_counts["team_passing_epa"] += 1
        if all(any(item["rushing_epa"] is not None for item in items)
               for items in team_counts.values()):
            metric_counts["team_rushing_epa"] += 1
        if all(any(item["passing_interceptions"] is not None
                   or item["rushing_fumbles_lost"] is not None for item in items)
               for items in team_counts.values()):
            metric_counts["team_turnover_data"] += 1

        for key, metric in (
            ("pbp_offensive_epa", "epa_n"),
            ("pbp_success_rate", "success_n"),
            ("pbp_third_down_rate", "third_n"),
        ):
            both = True
            for team in team_counts:
                entries = [
                    item for (entry_team, _), item in pbp_history.items()
                    if entry_team == team and item["kickoff"] < cutoff
                    and item[metric] > 0
                ]
                if not entries:
                    both = False
                    break
            if both:
                metric_counts[key] += 1

        both_def = True
        for team in team_counts:
            entries = [
                item for (entry_team, _), item in pbp_history.items()
                if entry_team == "DEF:" + team and item["kickoff"] < cutoff
                and item["epa_n"] > 0
            ]
            if not entries:
                both_def = False
                break
        if both_def:
            metric_counts["pbp_defensive_epa_allowed"] += 1

    def coverage(count):
        return round(100.0 * count / target_count, 2) if target_count else 0.0

    return {
        "success": True,
        "sport": "NFL",
        "season": int(season),
        "model_version": "NFL-1.0.0",
        "read_only": True,
        "model_impact": "none",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "target_games": "Todos los partidos de temporada regular con kickoff válido.",
            "pregame_cutoff": "Solo estadísticas de partidos completados cuyo kickoff sea estrictamente anterior al del partido objetivo.",
            "same_game_excluded": True,
            "future_games_excluded": True,
            "interpretation": "Cobertura de datos, no prueba de mejora predictiva ni validación del modelo.",
        },
        "target_games": target_count,
        "completed_games_available_for_join": len(completed),
        "sources": sources,
        "history_depth": [
            {"minimum_prior_games_per_team": threshold, "games_with_both_teams": count,
             "coverage_pct": coverage(count)}
            for threshold, count in history_thresholds.items()
        ],
        "candidate_feature_coverage": [
            {"feature": feature, "games_with_both_teams": count,
             "coverage_pct": coverage(count)}
            for feature, count in metric_counts.items()
        ],
        "next_step": "Validar integridad y calcular predicciones históricas walk-forward con estas variables en modo experimental.",
    }
