import math
import requests
from datetime import datetime, timezone

MLB_API = "https://statsapi.mlb.com/api/v1"


def clamp(value, minimum=0.05, maximum=0.95):
    return max(minimum, min(maximum, value))


def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers={
            "User-Agent": "Sports-Predictor/1.0"
        }
    )

    response.raise_for_status()
    return response.json()


def get_game(game_id):
    url = f"{MLB_API}.1/game/{game_id}/feed/live"
    return get_json(url)


def get_team_season_stats(team_id, season=2026):
    url = f"{MLB_API}/teams/{team_id}/stats"

    params = {
        "stats": "season",
        "group": "hitting,pitching",
        "season": season
    }

    data = get_json(url, params)

    result = {
        "hitting": {},
        "pitching": {}
    }

    for split in data.get("stats", []):
        group = split.get("group", {}).get("displayName", "").lower()

        if group == "hitting":
            result["hitting"] = split.get("splits", [{}])[0].get(
                "stat", {}
            )

        elif group == "pitching":
            result["pitching"] = split.get("splits", [{}])[0].get(
                "stat", {}
            )

    return result


def get_player_pitching_stats(player_id, season=2026):
    if not player_id:
        return {}

    url = f"{MLB_API}/people/{player_id}/stats"

    params = {
        "stats": "season",
        "group": "pitching",
        "season": season
    }

    data = get_json(url, params)

    splits = data.get("stats", [{}])[0].get("splits", [])

    if not splits:
        return {}

    return splits[0].get("stat", {})


def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_probability(
    home_hitting,
    away_hitting,
    home_pitching,
    away_pitching,
    home_pitcher,
    away_pitcher
):
    home_score = 0.50

    # Offensive comparison
    home_ops = safe_float(home_hitting.get("ops"), 0.700)
    away_ops = safe_float(away_hitting.get("ops"), 0.700)

    offensive_difference = home_ops - away_ops
    home_score += offensive_difference * 0.35

    # Team pitching comparison.
    # Lower ERA is better.
    home_era = safe_float(home_pitching.get("era"), 4.50)
    away_era = safe_float(away_pitching.get("era"), 4.50)

    pitching_difference = away_era - home_era
    home_score += pitching_difference * 0.035

    # Starting pitcher comparison.
    home_sp_era = safe_float(home_pitcher.get("era"))
    away_sp_era = safe_float(away_pitcher.get("era"))

    if home_sp_era is not None and away_sp_era is not None:
        home_score += (away_sp_era - home_sp_era) * 0.025

    # Home field advantage.
    home_score += 0.025

    probability = clamp(home_score)

    return {
        "home": round(probability, 4),
        "away": round(1 - probability, 4)
    }


def analyze_mlb_game(game_id):
    game = get_game(game_id)

    game_data = game.get("gameData", {})
    live_data = game.get("liveData", {})

    status = game_data.get("status", {}).get("abstractGameState")

    teams = game_data.get("teams", {})

    home_team = teams.get("home", {})
    away_team = teams.get("away", {})

    home_id = home_team.get("id")
    away_id = away_team.get("id")

    home_name = home_team.get("name")
    away_name = away_team.get("name")

    venue = game_data.get("venue", {}).get("name")

    datetime_value = game_data.get("datetime", {}).get(
        "dateTime"
    )

    # We only want pregame analysis.
    if status in {"Final", "Live"}:
        return {
            "success": False,
            "message": (
                "Este partido ya comenzó o terminó. "
                "El motor pregame no utilizará información "
                "posterior al inicio del partido."
            ),
            "game_id": str(game_id),
            "status": status
        }

    home_stats = get_team_season_stats(home_id)
    away_stats = get_team_season_stats(away_id)

    probable_pitchers = (
        game_data
        .get("probablePitchers", {})
    )

    home_pitcher_info = probable_pitchers.get("home", {})
    away_pitcher_info = probable_pitchers.get("away", {})

    home_pitcher_id = home_pitcher_info.get("id")
    away_pitcher_id = away_pitcher_info.get("id")

    home_pitcher_stats = get_player_pitching_stats(
        home_pitcher_id
    )

    away_pitcher_stats = get_player_pitching_stats(
        away_pitcher_id
    )

    probabilities = calculate_probability(
        home_stats["hitting"],
        away_stats["hitting"],
        home_stats["pitching"],
        away_stats["pitching"],
        home_pitcher_stats,
        away_pitcher_stats
    )

    factors = {
        "home_advantage": 0.025,
        "home_team_ops": home_stats["hitting"].get("ops"),
        "away_team_ops": away_stats["hitting"].get("ops"),
        "home_team_era": home_stats["pitching"].get("era"),
        "away_team_era": away_stats["pitching"].get("era"),
        "home_pitcher_era": home_pitcher_stats.get("era"),
        "away_pitcher_era": away_pitcher_stats.get("era")
    }

    confidence = abs(
        probabilities["home"] -
        probabilities["away"]
    )

    confidence = clamp(
        0.50 + confidence * 0.75,
        0.50,
        0.90
    )

    predicted_team = (
        home_name
        if probabilities["home"] >= probabilities["away"]
        else away_name
    )

    return {
        "success": True,
        "model_version": "1.1.0-baseline",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "game": {
            "game_id": str(game_id),
            "date": datetime_value,
            "status": status,
            "venue": venue,
            "home": home_name,
            "away": away_name
        },

        "prediction": {
            "winner": predicted_team,
            "home_probability": probabilities["home"],
            "away_probability": probabilities["away"],
            "confidence": round(confidence, 4)
        },

        "factors": factors
    }
