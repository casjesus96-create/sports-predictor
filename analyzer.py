import requests
from datetime import datetime, timezone

from form_engine import get_matchup_form
from matchup_engine import get_matchup_data
from prediction import (
    MODEL_VERSION,
    calculate_probability,
    calculate_recent_form_score,
    calculate_run_form_score,
)

MLB_API = "https://statsapi.mlb.com/api/v1"
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1"
MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0",
    "Accept": "application/json",
}


def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers=MLB_HEADERS,
    )
    response.raise_for_status()
    return response.json()


def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_game(game_id):
    return get_json(f"{MLB_GAME_API}/game/{game_id}/feed/live")


def get_team_season_stats(team_id, season=2026):
    result = {"hitting": {}, "pitching": {}}
    for group in ("hitting", "pitching"):
        data = get_json(
            f"{MLB_API}/teams/{int(team_id)}/stats",
            {"stats": "season", "group": group, "season": int(season)},
        )
        for stat_group in data.get("stats") or []:
            splits = stat_group.get("splits") or []
            if splits:
                stats = splits[0].get("stat") or {}
                if stats:
                    result[group] = stats
                    break
    return result


def get_player_pitching_stats(player_id, season=2026):
    if not player_id:
        return {}
    data = get_json(
        f"{MLB_API}/people/{int(player_id)}/stats",
        {"stats": "season", "group": "pitching", "season": int(season)},
    )
    for stat_group in data.get("stats") or []:
        splits = stat_group.get("splits") or []
        if splits:
            return splits[0].get("stat") or {}
    return {}


def _stat_value(stats, *keys):
    for key in keys:
        if stats.get(key) is not None:
            return stats.get(key)
    return None


def _empty_form():
    return {"last_5": {}, "last_10": {}, "last_15": {}}


def analyze_mlb_game(game_id):
    """Orquestador pregame del único modelo oficial MLB 2.0.0-matchup."""
    game = get_game(game_id)
    game_data = game.get("gameData", {})
    status_data = game_data.get("status", {})
    status = status_data.get("abstractGameState")
    detailed_status = status_data.get("detailedState")

    if status in {"Final", "Live"}:
        return {
            "success": False,
            "message": (
                "Este partido ya comenzó o terminó. El motor pregame "
                "no utilizará información posterior al inicio del partido."
            ),
            "game_id": str(game_id),
            "status": status,
            "detailed_status": detailed_status,
        }

    teams = game_data.get("teams", {})
    home_team = teams.get("home", {})
    away_team = teams.get("away", {})
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    home_name = home_team.get("name")
    away_name = away_team.get("name")

    if not home_id or not away_id:
        raise ValueError("No se pudieron determinar los equipos del partido.")

    venue = game_data.get("venue", {}).get("name")
    datetime_value = game_data.get("datetime", {}).get("dateTime")

    home_stats = get_team_season_stats(home_id, 2026)
    away_stats = get_team_season_stats(away_id, 2026)

    probable = game_data.get("probablePitchers", {})
    home_feed_pitcher = probable.get("home", {})
    away_feed_pitcher = probable.get("away", {})
    home_pitcher_id = home_feed_pitcher.get("id")
    away_pitcher_id = away_feed_pitcher.get("id")

    form_error = None
    try:
        matchup_form = get_matchup_form(
            home_team_id=home_id,
            away_team_id=away_id,
            before_date=datetime_value,
        )
        home_form = matchup_form.get("home", {})
        away_form = matchup_form.get("away", {})
    except Exception as exc:
        form_error = str(exc)
        home_form = _empty_form()
        away_form = _empty_form()

    # Fuente canónica del matchup: incluye pitchers, H2H, splits y bullpen.
    matchup_error = None
    try:
        matchup_data = get_matchup_data(
            game_id=game_id,
            home_team_id=home_id,
            away_team_id=away_id,
            before_date=datetime_value,
            season=2026,
            game_type="R",
        ) or {}
    except Exception as exc:
        matchup_error = str(exc)
        matchup_data = {}

    matchup_pitchers = matchup_data.get("pitchers") or {}
    matchup_home_pitcher = matchup_pitchers.get("home") or {}
    matchup_away_pitcher = matchup_pitchers.get("away") or {}

    home_pitcher_id = (
        matchup_home_pitcher.get("pitcher_id")
        or matchup_home_pitcher.get("id")
        or home_pitcher_id
    )
    away_pitcher_id = (
        matchup_away_pitcher.get("pitcher_id")
        or matchup_away_pitcher.get("id")
        or away_pitcher_id
    )

    home_pitcher_name = (
        matchup_home_pitcher.get("pitcher_name")
        or matchup_home_pitcher.get("name")
        or home_feed_pitcher.get("fullName")
        or home_feed_pitcher.get("name")
    )
    away_pitcher_name = (
        matchup_away_pitcher.get("pitcher_name")
        or matchup_away_pitcher.get("name")
        or away_feed_pitcher.get("fullName")
        or away_feed_pitcher.get("name")
    )

    # Los IDs canónicos se usan una sola vez para las estadísticas de pitchers.
    home_pitcher_stats = get_player_pitching_stats(home_pitcher_id, 2026)
    away_pitcher_stats = get_player_pitching_stats(away_pitcher_id, 2026)

    home_hitting = home_stats.get("hitting") or {}
    away_hitting = away_stats.get("hitting") or {}
    home_pitching = home_stats.get("pitching") or {}
    away_pitching = away_stats.get("pitching") or {}

    # ÚNICA llamada al modelo oficial.
    probabilities = calculate_probability(
        home_hitting,
        away_hitting,
        home_pitching,
        away_pitching,
        home_pitcher_stats,
        away_pitcher_stats,
        home_form,
        away_form,
    )

    factors = {
        "home_advantage": 0.025,
        "home_team_ops": home_hitting.get("ops"),
        "away_team_ops": away_hitting.get("ops"),
        "home_team_era": home_pitching.get("era"),
        "away_team_era": away_pitching.get("era"),
        "home_pitcher_era": home_pitcher_stats.get("era"),
        "away_pitcher_era": away_pitcher_stats.get("era"),
        "offense": {
            "home": {
                "hits": _stat_value(home_hitting, "hits"),
                "home_runs": _stat_value(home_hitting, "homeRuns", "home_runs"),
                "strikeouts": _stat_value(home_hitting, "strikeOuts", "strikeouts"),
                "runs": _stat_value(home_hitting, "runs"),
                "walks": _stat_value(home_hitting, "baseOnBalls", "walks"),
                "avg": _stat_value(home_hitting, "avg"),
                "obp": _stat_value(home_hitting, "obp"),
                "slg": _stat_value(home_hitting, "slg"),
                "ops": _stat_value(home_hitting, "ops"),
            },
            "away": {
                "hits": _stat_value(away_hitting, "hits"),
                "home_runs": _stat_value(away_hitting, "homeRuns", "home_runs"),
                "strikeouts": _stat_value(away_hitting, "strikeOuts", "strikeouts"),
                "runs": _stat_value(away_hitting, "runs"),
                "walks": _stat_value(away_hitting, "baseOnBalls", "walks"),
                "avg": _stat_value(away_hitting, "avg"),
                "obp": _stat_value(away_hitting, "obp"),
                "slg": _stat_value(away_hitting, "slg"),
                "ops": _stat_value(away_hitting, "ops"),
            },
        },
        "pitching": {
            "home": {
                "era": _stat_value(home_pitching, "era"),
                "whip": _stat_value(home_pitching, "whip"),
                "strikeouts": _stat_value(home_pitching, "strikeOuts", "strikeouts"),
                "hits_allowed": _stat_value(home_pitching, "hits"),
                "home_runs_allowed": _stat_value(home_pitching, "homeRuns", "home_runs"),
                "walks": _stat_value(home_pitching, "baseOnBalls", "walks"),
            },
            "away": {
                "era": _stat_value(away_pitching, "era"),
                "whip": _stat_value(away_pitching, "whip"),
                "strikeouts": _stat_value(away_pitching, "strikeOuts", "strikeouts"),
                "hits_allowed": _stat_value(away_pitching, "hits"),
                "home_runs_allowed": _stat_value(away_pitching, "homeRuns", "home_runs"),
                "walks": _stat_value(away_pitching, "baseOnBalls", "walks"),
            },
        },
        "probable_pitchers": {
            "home": {
                **matchup_home_pitcher,
                "pitcher_id": home_pitcher_id,
                "id": home_pitcher_id,
                "pitcher_name": home_pitcher_name,
                "name": home_pitcher_name,
                "pitcher_hand": matchup_home_pitcher.get("pitcher_hand"),
                "stats": home_pitcher_stats,
            },
            "away": {
                **matchup_away_pitcher,
                "pitcher_id": away_pitcher_id,
                "id": away_pitcher_id,
                "pitcher_name": away_pitcher_name,
                "name": away_pitcher_name,
                "pitcher_hand": matchup_away_pitcher.get("pitcher_hand"),
                "stats": away_pitcher_stats,
            },
        },
        "matchup": matchup_data,
        # El bullpen llega exclusivamente desde matchup_engine.py.
        "bullpen": matchup_data.get("bullpen", {
            "available": False,
            "difference": 0.0,
            "signal": 0.0,
            "confidence": 0.0,
        }),
        "team_season_stats": {
            "home": {"hitting": home_hitting, "pitching": home_pitching},
            "away": {"hitting": away_hitting, "pitching": away_pitching},
        },
        "recent_form": {"home": home_form, "away": away_form},
        "recent_form_score": {
            "home": calculate_recent_form_score(home_form),
            "away": calculate_recent_form_score(away_form),
        },
        "recent_run_differential_per_game": {
            "home": calculate_run_form_score(home_form),
            "away": calculate_run_form_score(away_form),
        },
    }

    if form_error:
        factors["form_engine_error"] = form_error
    if matchup_error:
        factors["matchup_engine_error"] = matchup_error

    probability_difference = abs(
        probabilities["home"] - probabilities["away"]
    )
    confidence = max(
        0.50,
        min(0.90, 0.50 + probability_difference * 0.75),
    )

    predicted_team = (
        home_name
        if probabilities["home"] >= probabilities["away"]
        else away_name
    )

    home_form_games = home_form.get("last_15", {}).get("games", 0)
    away_form_games = away_form.get("last_15", {}).get("games", 0)
    if home_form_games >= 15 and away_form_games >= 15:
        data_quality = 100
    elif home_form_games >= 10 and away_form_games >= 10:
        data_quality = 90
    elif home_form_games >= 5 and away_form_games >= 5:
        data_quality = 80
    else:
        data_quality = 65

    if form_error or matchup_error:
        data_quality = min(data_quality, 70)

    return {
        "success": True,
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "game": {
            "game_id": str(game_id),
            "date": datetime_value,
            "status": status,
            "detailed_status": detailed_status,
            "venue": venue,
            "home": home_name,
            "away": away_name,
            "home_team_id": home_id,
            "away_team_id": away_id,
        },
        "prediction": {
            "winner": predicted_team,
            "home_probability": probabilities["home"],
            "away_probability": probabilities["away"],
            "confidence": round(confidence, 4),
            "data_quality": data_quality,
        },
        "factors": factors,
    }
