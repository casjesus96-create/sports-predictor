"""Data-coverage scoring for MLB pregame analysis.

This module describes input availability only. It never changes model
probabilities and never treats a missing value as a real zero.
"""
import math


def _has_numeric_value(value):
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def _has_pitcher_stats(stats):
    if not isinstance(stats, dict):
        return False
    # ERA and WHIP can legitimately be 0.00; presence is what matters.
    return any(
        _has_numeric_value(stats.get(key))
        for key in ("era", "whip", "inningsPitched", "strikeOuts", "strikeouts")
    )


def _games_count(form):
    if not isinstance(form, dict):
        return 0
    last_15 = form.get("last_15")
    if not isinstance(last_15, dict):
        return 0
    value = last_15.get("games")
    if not _has_numeric_value(value):
        return 0
    return max(0, min(15, int(float(value))))


def calculate_data_coverage(
    home_hitting,
    away_hitting,
    home_pitching,
    away_pitching,
    home_pitcher_id,
    away_pitcher_id,
    home_pitcher_stats,
    away_pitcher_stats,
    home_form,
    away_form,
):
    """Return a 0-100 coverage score, component detail, and missing fields."""
    home_hitting = home_hitting if isinstance(home_hitting, dict) else {}
    away_hitting = away_hitting if isinstance(away_hitting, dict) else {}
    home_pitching = home_pitching if isinstance(home_pitching, dict) else {}
    away_pitching = away_pitching if isinstance(away_pitching, dict) else {}
    home_pitcher_stats = home_pitcher_stats if isinstance(home_pitcher_stats, dict) else {}
    away_pitcher_stats = away_pitcher_stats if isinstance(away_pitcher_stats, dict) else {}

    home_games = _games_count(home_form)
    away_games = _games_count(away_form)

    components = {
        "home_team_ops": {
            "available": _has_numeric_value(home_hitting.get("ops")),
            "weight": 12.5,
        },
        "away_team_ops": {
            "available": _has_numeric_value(away_hitting.get("ops")),
            "weight": 12.5,
        },
        "home_team_era": {
            "available": _has_numeric_value(home_pitching.get("era")),
            "weight": 12.5,
        },
        "away_team_era": {
            "available": _has_numeric_value(away_pitching.get("era")),
            "weight": 12.5,
        },
        "home_starter_stats": {
            "available": bool(home_pitcher_id) and _has_pitcher_stats(home_pitcher_stats),
            "weight": 12.5,
        },
        "away_starter_stats": {
            "available": bool(away_pitcher_id) and _has_pitcher_stats(away_pitcher_stats),
            "weight": 12.5,
        },
        "home_recent_form": {
            "available": home_games > 0,
            "games": home_games,
            "target_games": 15,
            "coverage": home_games / 15,
            "weight": 12.5,
        },
        "away_recent_form": {
            "available": away_games > 0,
            "games": away_games,
            "target_games": 15,
            "coverage": away_games / 15,
            "weight": 12.5,
        },
    }

    score = 0.0
    missing_fields = []
    for name, component in components.items():
        if name.endswith("_recent_form"):
            score += component["weight"] * component["coverage"]
            if component["coverage"] < 1.0:
                missing_fields.append(name)
        elif component["available"]:
            score += component["weight"]
        else:
            missing_fields.append(name)

    score = int(round(max(0.0, min(100.0, score))))
    available_count = sum(
        1 for component in components.values()
        if component["available"]
    )

    return {
        "score": score,
        "available_components": available_count,
        "total_components": len(components),
        "complete": not missing_fields and home_games >= 15 and away_games >= 15,
        "components": components,
        "missing_fields": missing_fields,
        "method": "weighted_input_coverage_v1",
        "note": (
            "Mide disponibilidad de datos, no calidad predictiva ni probabilidad "
            "de acierto. Los campos ausentes no se convierten en cero."
        ),
    }
