"""Modelo oficial NBA-1.0.0. Solo usa información disponible antes del inicio."""
import math

MODEL_VERSION = "NBA-1.1.0"


def _clamp(value, low, high):
    return max(low, min(high, value))


def _number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def predict_winner(home_history, away_history, neutral_site=False):
    """Calcula probabilidad binaria con ratings de margen y forma reciente."""
    home_n = int(home_history.get("games") or 0)
    away_n = int(away_history.get("games") or 0)
    home_diff = _number(home_history.get("point_diff_per_game"))
    away_diff = _number(away_history.get("point_diff_per_game"))
    home_recent = _number(home_history.get("recent_point_diff_per_game"))
    away_recent = _number(away_history.get("recent_point_diff_per_game"))
    home_win = _number(home_history.get("win_rate"), 0.5)
    away_win = _number(away_history.get("win_rate"), 0.5)
    home_recent_win = _number(home_history.get("recent_win_rate"), 0.5)
    away_recent_win = _number(away_history.get("recent_win_rate"), 0.5)

    # Aporte secundario de boxscore reciente. Si ESPN no ofrece una métrica,
    # su diferencia es cero y no se inventan estadísticas.
    home_stats = home_history.get("recent_stats_per_game") or {}
    away_stats = away_history.get("recent_stats_per_game") or {}

    def stat_edge(key, weight, invert=False):
        home_value = home_stats.get(key)
        away_value = away_stats.get(key)
        if home_value is None or away_value is None:
            return 0.0
        difference = _number(home_value) - _number(away_value)
        return (-difference if invert else difference) * weight

    boxscore_edge = (
        stat_edge("rebounds", 0.10)
        + stat_edge("assists", 0.12)
        + stat_edge("blocks", 0.25)
        + stat_edge("steals", 0.15)
        + stat_edge("turnovers", 0.12, invert=True)
        + stat_edge("field_goal_pct", 0.05)
        + stat_edge("three_point_pct", 0.025)
        + stat_edge("free_throw_pct", 0.01)
    )
    boxscore_edge = _clamp(boxscore_edge, -4.0, 4.0)

    # Regulariza las muestras pequeñas hacia valores neutrales.
    home_reliability = home_n / (home_n + 8.0)
    away_reliability = away_n / (away_n + 8.0)
    season_edge = home_diff * home_reliability - away_diff * away_reliability
    recent_edge = (
        home_recent * min(1.0, home_history.get("recent_games", 0) / 5.0)
        - away_recent * min(1.0, away_history.get("recent_games", 0) / 5.0)
    )
    win_edge = (
        (home_win - 0.5) * 5.0 * home_reliability
        - (away_win - 0.5) * 5.0 * away_reliability
    )
    recent_win_edge = (home_recent_win - away_recent_win) * 2.5
    home_advantage = 0.0 if neutral_site else 2.2

    # Margen esperado se transforma suavemente en probabilidad.
    expected_margin = (
        0.55 * season_edge
        + 0.20 * recent_edge
        + 0.15 * win_edge
        + 0.10 * recent_win_edge
        + home_advantage
    )
    probability_home = 1.0 / (1.0 + math.exp(-_clamp(expected_margin / 8.5, -6, 6)))
    probability_home = _clamp(probability_home, 0.08, 0.92)
    probability_away = 1.0 - probability_home

    sample_quality = min(100, round((home_n + away_n) / 2 / 15 * 100))
    if home_n == 0 or away_n == 0:
        data_quality = min(35, sample_quality)
    else:
        data_quality = max(25, sample_quality)

    winner = "HOME" if probability_home >= probability_away else "AWAY"
    return {
        "model_version": MODEL_VERSION,
        "winner": winner,
        "home_probability": round(probability_home, 4),
        "away_probability": round(probability_away, 4),
        "confidence": round(max(probability_home, probability_away), 4),
        "data_quality": int(data_quality),
        "expected_margin_home": round(expected_margin, 2),
        "recent_boxscore_edge": round(boxscore_edge, 2),
        "sample_size_home": home_n,
        "sample_size_away": away_n,
    }
