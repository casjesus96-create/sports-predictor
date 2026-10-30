"""Transparent NFL score projections, separate from sportsbook market lines."""


def _number(source, key):
    try:
        value = float(source.get(key))
        return value if value >= 0 and value < float("inf") else None
    except (TypeError, ValueError):
        return None


def project_score_lines(home_history, away_history, game):
    """Estimate points from pregame scoring/allowance history only.

    Per-team estimate = 55% of own points scored per game + 45% of
    opponent points allowed per game. Add a transparent 1.5-point home
    adjustment to the home estimate. Baseline only; validate chronologically.
    """
    home_games = int(home_history.get("games") or 0)
    away_games = int(away_history.get("games") or 0)
    market = {"spread_line": game.get("spread_line"), "total_line": game.get("total_line"), "source": "nflverse schedule"}
    if home_games < 1 or away_games < 1:
        return {"available": False, "reason": "Se necesita al menos un partido histórico de cada equipo.", "market": market}

    home_for = _number(home_history, "points_for_per_game")
    home_against = _number(home_history, "points_against_per_game")
    away_for = _number(away_history, "points_for_per_game")
    away_against = _number(away_history, "points_against_per_game")
    if None in (home_for, home_against, away_for, away_against):
        return {"available": False, "reason": "Faltan estadísticas válidas para estimar los puntos.", "market": market}

    projected_home = round(max(0.0, min(50.0, 0.55 * home_for + 0.45 * away_against + 1.5)), 1)
    projected_away = round(max(0.0, min(50.0, 0.55 * away_for + 0.45 * home_against)), 1)
    projected_total = round(projected_home + projected_away, 1)
    projected_margin = round(projected_home - projected_away, 1)
    market_total = _number(game, "total_line")
    return {
        "available": True,
        "projected_home_points": projected_home,
        "projected_away_points": projected_away,
        "projected_total_points": projected_total,
        "projected_home_margin": projected_margin,
        "home_advantage_points": 1.5,
        "formula": "0.55 × puntos a favor propios + 0.45 × puntos permitidos del rival; +1.5 localía",
        "sample": {"home_games": home_games, "away_games": away_games},
        "market": market,
        "market_comparison": {"total_difference": round(projected_total - market_total, 1) if market_total is not None else None},
    }
