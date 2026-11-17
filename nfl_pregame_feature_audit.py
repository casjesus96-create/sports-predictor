"""Chronological, read-only audit of NFL pregame feature availability."""
import csv
import gzip
import io
import math
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
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
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
            "passing_yards": _number(row, "passing_yards"),
            "rushing_yards": _number(row, "rushing_yards"),
            "passing_tds": _number(row, "passing_tds"),
            "rushing_tds": _number(row, "rushing_tds"),
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
        yards = _number(row, "yards_gained")
        pass_td = _number(row, "pass_touchdown")
        rush_td = _number(row, "rush_touchdown")
        sack = _number(row, "sack")
        interception = _number(row, "interception")
        fumble_lost = _number(row, "fumble_lost")
        third_converted = _truthy(row.get("third_down_converted"))
        fourth_converted = _truthy(row.get("fourth_down_converted"))

        def new_bucket():
            return {
                "game_id": game_id, "kickoff": kickoff, "epa_sum": 0.0, "epa_n": 0,
                "success_n": 0, "success_yes": 0,
                "third_n": 0, "third_yes": 0,
                "fourth_n": 0, "fourth_yes": 0,
                "yards_sum": 0.0, "yards_n": 0,
                "game_id": game_id, "plays_n": 0, "pass_td_n": 0, "rush_td_n": 0, "td_data_n": 0,
                "pass_td_total": 0, "rush_td_total": 0,
                "sacks_n": 0, "sacks_total": 0,
                "interceptions_n": 0, "interceptions_total": 0,
                "fumbles_lost_n": 0, "fumbles_lost_total": 0,
                "turnover_data_n": 0,
            }

        if offense:
            bucket = pbp_history.setdefault((offense, game_id), new_bucket())
            bucket["plays_n"] += 1
            if epa is not None:
                bucket["epa_sum"] += epa
                bucket["epa_n"] += 1
            if success is not None:
                bucket["success_n"] += 1
                bucket["success_yes"] += int(success > 0)
            if yards is not None:
                bucket["yards_sum"] += yards
                bucket["yards_n"] += 1
            if down == 3:
                bucket["third_n"] += 1
                bucket["third_yes"] += int(third_converted)
            if down == 4:
                bucket["fourth_n"] += 1
                bucket["fourth_yes"] += int(fourth_converted)
            if pass_td is not None:
                bucket["pass_td_n"] += 1
                bucket["pass_td_total"] += int(pass_td > 0)
                bucket["td_data_n"] += 1
            if rush_td is not None:
                bucket["rush_td_n"] += 1
                bucket["rush_td_total"] += int(rush_td > 0)
                bucket["td_data_n"] += 1
            if sack is not None:
                bucket["sacks_n"] += 1
                bucket["sacks_total"] += int(sack > 0)
            if interception is not None:
                bucket["interceptions_n"] += 1
                bucket["interceptions_total"] += int(interception > 0)
                bucket["turnover_data_n"] += 1
            if fumble_lost is not None:
                bucket["fumbles_lost_n"] += 1
                bucket["fumbles_lost_total"] += int(fumble_lost > 0)
                bucket["turnover_data_n"] += 1

        if defense:
            bucket = pbp_history.setdefault(("DEF:" + defense, game_id), new_bucket())
            if epa is not None:
                bucket["epa_sum"] += epa
                bucket["epa_n"] += 1
            if yards is not None:
                bucket["yards_sum"] += yards
                bucket["yards_n"] += 1
            if pass_td is not None:
                bucket["pass_td_n"] += 1
                bucket["td_data_n"] += 1
            if rush_td is not None:
                bucket["rush_td_n"] += 1
                bucket["td_data_n"] += 1
            if sack is not None:
                bucket["sacks_n"] += 1
            if interception is not None:
                bucket["interceptions_n"] += 1
                bucket["turnover_data_n"] += 1
            if fumble_lost is not None:
                bucket["fumbles_lost_n"] += 1
                bucket["turnover_data_n"] += 1

    targets = [
        game for game in games
        if game.get("game_type") == "REG"
        and game.get("home") and game.get("away")
        and _parse_time(game.get("kickoff"))
    ]
    target_count = len(targets)

    def _mean(values):
        usable = [value for value in values if value is not None and math.isfinite(value)]
        return round(sum(usable) / len(usable), 3) if usable else None

    advanced_team_profiles = []
    for target in targets:
        cutoff = _parse_time(target["kickoff"])
        profile = {
            "game_id": str(target.get("game_id")),
            "kickoff": target.get("kickoff"),
            "home": str(target.get("home") or ""),
            "away": str(target.get("away") or ""),
            "window_games": 5,
            "teams": {},
        }
        for team in (target["home"], target["away"]):
            team_key = str(team).upper()
            prior_team_rows = [
                item for item in team_history.get(team_key, [])
                if item["kickoff"] is not None and item["kickoff"] < cutoff
            ]
            prior_team_rows = list({item["game_id"]: item for item in prior_team_rows}.values())
            prior_team_rows.sort(key=lambda item: item["kickoff"])
            prior_team_rows = prior_team_rows[-5:]
            prior_ids = {item["game_id"] for item in prior_team_rows}
            offense_rows = [
                item for (entry_team, _), item in pbp_history.items()
                if entry_team == team_key and item["kickoff"] < cutoff
                and item.get("game_id") in prior_ids
            ]
            defense_rows = [
                item for (entry_team, _), item in pbp_history.items()
                if entry_team == "DEF:" + team_key and item["kickoff"] < cutoff
                and item.get("game_id") in prior_ids
            ]

            def _ratio(numerator, denominator):
                return round(numerator / denominator, 4) if denominator else None

            off_epa_n = sum(item["epa_n"] for item in offense_rows)
            off_epa_sum = sum(item["epa_sum"] for item in offense_rows)
            success_n = sum(item["success_n"] for item in offense_rows)
            success_yes = sum(item["success_yes"] for item in offense_rows)
            yards_n = sum(item["yards_n"] for item in offense_rows)
            yards_sum = sum(item["yards_sum"] for item in offense_rows)
            third_n = sum(item["third_n"] for item in offense_rows)
            third_yes = sum(item["third_yes"] for item in offense_rows)
            fourth_n = sum(item["fourth_n"] for item in offense_rows)
            fourth_yes = sum(item["fourth_yes"] for item in offense_rows)
            def_epa_n = sum(item["epa_n"] for item in defense_rows)
            def_epa_sum = sum(item["epa_sum"] for item in defense_rows)
            def_yards_n = sum(item["yards_n"] for item in defense_rows)
            def_yards_sum = sum(item["yards_sum"] for item in defense_rows)

            profile["teams"][team_key] = {
                "games_sampled": len(prior_team_rows),
                "sample_game_ids": [item["game_id"] for item in prior_team_rows],
                "passing_yards_per_game": _mean([item.get("passing_yards") for item in prior_team_rows]),
                "rushing_yards_per_game": _mean([item.get("rushing_yards") for item in prior_team_rows]),
                "passing_touchdowns_per_game": _mean([item.get("passing_tds") for item in prior_team_rows]),
                "rushing_touchdowns_per_game": _mean([item.get("rushing_tds") for item in prior_team_rows]),
                "interceptions_per_game": _mean([item.get("passing_interceptions") for item in prior_team_rows]),
                "fumbles_lost_per_game": _mean([item.get("rushing_fumbles_lost") for item in prior_team_rows]),
                "turnovers_per_game": _mean([
                    item.get("interceptions_total", 0) + item.get("fumbles_lost_total", 0)
                    if item.get("turnover_data_n", 0) else None for item in offense_rows
                ]),
                "offensive_interceptions_per_game": _mean([
                    item.get("interceptions_total") if item.get("interceptions_n", 0) else None
                    for item in offense_rows
                ]),
                "offensive_fumbles_lost_per_game": _mean([
                    item.get("fumbles_lost_total") if item.get("fumbles_lost_n", 0) else None
                    for item in offense_rows
                ]),
                "sacks_suffered_per_game": _mean([item.get("sacks_suffered") for item in prior_team_rows]),
                "passing_epa_per_game": _mean([item.get("passing_epa") for item in prior_team_rows]),
                "rushing_epa_per_game": _mean([item.get("rushing_epa") for item in prior_team_rows]),
                "offensive_epa_per_play": _ratio(off_epa_sum, off_epa_n),
                "offensive_success_rate": _ratio(success_yes, success_n),
                "offensive_yards_per_play": _ratio(yards_sum, yards_n),
                "third_down_conversion_rate": _ratio(third_yes, third_n),
                "fourth_down_conversion_rate": _ratio(fourth_yes, fourth_n),
                "defensive_epa_allowed_per_play": _ratio(def_epa_sum, def_epa_n),
                "defensive_yards_allowed_per_play": _ratio(def_yards_sum, def_yards_n),
                "defensive_touchdowns_allowed_per_game": _mean([
                    item.get("pass_td_total", 0) + item.get("rush_td_total", 0)
                    if item.get("td_data_n", 0) else None for item in defense_rows
                ]),
                "defensive_sacks_per_game": _mean([
                    item.get("sacks_total") if item.get("sacks_n", 0) else None
                    for item in defense_rows
                ]),
                "defensive_interceptions_per_game": _mean([item.get("interceptions_total") for item in defense_rows]),
                "defensive_fumbles_recovered_per_game": _mean([item.get("fumbles_lost_total") for item in defense_rows]),
                "defensive_turnovers_per_game": _mean([
                    item.get("interceptions_total", 0) + item.get("fumbles_lost_total", 0)
                    if item.get("turnover_data_n", 0) else None for item in defense_rows
                ]),
                "offensive_plays_sampled": sum(item["plays_n"] for item in offense_rows),
                "third_down_attempts": third_n,
                "fourth_down_attempts": fourth_n,
            }
        advanced_team_profiles.append(profile)

    history_thresholds = {1: 0, 3: 0, 5: 0}
    metric_counts = {
        "team_passing_epa": 0,
        "team_rushing_epa": 0,
        "team_turnover_data": 0,
        "team_passing_yards": 0,
        "team_rushing_yards": 0,
        "team_passing_touchdowns": 0,
        "team_rushing_touchdowns": 0,
        "team_sacks_suffered": 0,
        "pbp_offensive_epa": 0,
        "pbp_success_rate": 0,
        "pbp_yards_per_play": 0,
        "pbp_offensive_touchdowns": 0,
        "pbp_third_down_rate": 0,
        "pbp_fourth_down_rate": 0,
        "pbp_defensive_epa_allowed": 0,
        "pbp_defensive_yards_allowed": 0,
        "pbp_defensive_touchdowns_allowed": 0,
        "pbp_defensive_sacks": 0,
        "pbp_defensive_turnovers": 0,
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

        team_feature_map = {
            "team_passing_yards": "passing_yards",
            "team_rushing_yards": "rushing_yards",
            "team_passing_touchdowns": "passing_tds",
            "team_rushing_touchdowns": "rushing_tds",
            "team_sacks_suffered": "sacks_suffered",
        }
        for output_key, field in team_feature_map.items():
            if all(any(item.get(field) is not None for item in items)
                   for items in team_counts.values()):
                metric_counts[output_key] += 1

        pbp_feature_map = {
            "pbp_offensive_epa": "epa_n",
            "pbp_success_rate": "success_n",
            "pbp_yards_per_play": "yards_n",
            "pbp_third_down_rate": "third_n",
            "pbp_fourth_down_rate": "fourth_n",
            "pbp_offensive_touchdowns": "td_data_n",
        }
        for output_key, field in pbp_feature_map.items():
            both = True
            for team in team_counts:
                entries = [
                    item for (entry_team, _), item in pbp_history.items()
                    if entry_team == team and item["kickoff"] < cutoff
                    and item[field] > 0
                ]
                if not entries:
                    both = False
                    break
            if both:
                metric_counts[output_key] += 1

        defensive_feature_map = {
            "pbp_defensive_epa_allowed": "epa_n",
            "pbp_defensive_yards_allowed": "yards_n",
            "pbp_defensive_touchdowns_allowed": "td_data_n",
            "pbp_defensive_sacks": "sacks_n",
            "pbp_defensive_turnovers": "turnover_data_n",
        }
        for output_key, field in defensive_feature_map.items():
            both = True
            for team in team_counts:
                entries = [
                    item for (entry_team, _), item in pbp_history.items()
                    if entry_team == "DEF:" + team and item["kickoff"] < cutoff
                    and item[field] > 0
                ]
                if not entries:
                    both = False
                    break
            if both:
                metric_counts[output_key] += 1

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
            "interpretation": "Cobertura de datos, no prueba de mejora predictiva ni validación del modelo. Los ceros observados son valores válidos; la cobertura exige al menos un registro previo con el campo disponible para ambos equipos.",
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
        "advanced_team_profiles": advanced_team_profiles,
        "advanced_team_profile_method": {
            "window": "Últimos 5 partidos completados disponibles antes del kickoff",
            "pregame_cutoff": "Cada partido del perfil debe tener kickoff estrictamente anterior al partido objetivo.",
            "rates": "EPA, éxito, yardas por jugada y conversiones se calculan sobre jugadas o intentos disponibles; se incluyen denominadores para terceras y cuartas oportunidades.",
            "missing_values": "null significa dato no disponible; no se sustituye por cero.",
            "read_only": True,
        },
        "next_step": "Validar integridad y calcular predicciones históricas walk-forward con estas variables en modo experimental.",
    }
