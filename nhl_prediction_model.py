"""Research-only NHL Elo model trained exclusively from approved own-archive rows.

Pure computation only: no fetching, database access, persistence, or official-model
promotion. No probability is returned until configured historical sample gates pass.
"""
from __future__ import annotations

from datetime import date
from math import pow
from typing import Any, Iterable

MODEL_VERSION = "NHL-ELO-RESEARCH-0.1.0"
DEFAULT_INITIAL_RATING = 1500.0
DEFAULT_HOME_ADVANTAGE = 35.0
DEFAULT_K_FACTOR = 20.0
DEFAULT_MIN_GAMES = 30
DEFAULT_MIN_TEAM_GAMES = 5


def _valid_final_game(row: dict[str, Any], game_type: int) -> bool:
    if not isinstance(row, dict) or row.get("training_eligible") is not True:
        return False
    if row.get("game_type") != game_type or game_type not in (2, 3):
        return False
    if str(row.get("result_status") or "").upper() != "FINAL":
        return False
    home = str(row.get("home_team_canonical_key") or "").strip().upper()
    away = str(row.get("away_team_canonical_key") or "").strip().upper()
    if not home or not away or home == away:
        return False
    hs, aws = row.get("home_score"), row.get("away_score")
    if (isinstance(hs, bool) or not isinstance(hs, int) or hs < 0
            or isinstance(aws, bool) or not isinstance(aws, int) or aws < 0 or hs == aws):
        return False
    try:
        date.fromisoformat(str(row.get("game_date") or ""))
    except ValueError:
        return False
    return True


def _expected_home(home_rating: float, away_rating: float, home_advantage: float) -> float:
    return 1.0 / (1.0 + pow(10.0, (away_rating - (home_rating + home_advantage)) / 400.0))


def build_elo_ratings(
    archive_rows: Iterable[dict[str, Any]],
    *,
    game_type: int = 2,
    as_of_date: str | None = None,
    initial_rating: float = DEFAULT_INITIAL_RATING,
    home_advantage: float = DEFAULT_HOME_ADVANTAGE,
    k_factor: float = DEFAULT_K_FACTOR,
) -> dict[str, Any]:
    """Replay eligible results chronologically; exclude games on/after cutoff."""
    if game_type not in (2, 3):
        raise ValueError("game_type debe ser 2 (temporada regular) o 3 (playoffs).")
    cutoff = date.fromisoformat(as_of_date) if as_of_date else None
    if initial_rating <= 0 or home_advantage < 0 or k_factor <= 0:
        raise ValueError("Los parámetros Elo deben ser positivos y válidos.")

    unique: dict[str, dict[str, Any]] = {}
    for row in archive_rows:
        if not _valid_final_game(row, game_type):
            continue
        if cutoff and date.fromisoformat(row["game_date"]) >= cutoff:
            continue
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            continue
        previous = unique.get(game_id)
        if previous is not None and previous != row:
            raise ValueError(f"game_id contradictorio en el archivo NHL: {game_id}")
        unique[game_id] = row

    ordered = sorted(unique.values(), key=lambda row: (row["game_date"], str(row["game_id"])))
    ratings: dict[str, float] = {}
    games_played: dict[str, int] = {}
    for row in ordered:
        home = str(row["home_team_canonical_key"]).strip().upper()
        away = str(row["away_team_canonical_key"]).strip().upper()
        rh = ratings.get(home, initial_rating)
        ra = ratings.get(away, initial_rating)
        expected = _expected_home(rh, ra, home_advantage)
        actual = 1.0 if row["home_score"] > row["away_score"] else 0.0
        margin_multiplier = min(1.0 + abs(row["home_score"] - row["away_score"]) * 0.1, 1.5)
        update = k_factor * margin_multiplier * (actual - expected)
        ratings[home] = rh + update
        ratings[away] = ra - update
        games_played[home] = games_played.get(home, 0) + 1
        games_played[away] = games_played.get(away, 0) + 1

    return {
        "model_version": MODEL_VERSION,
        "game_type": game_type,
        "as_of_date_exclusive": as_of_date,
        "games_used": len(ordered),
        "ratings": ratings,
        "games_played_by_team": games_played,
        "initial_rating": initial_rating,
        "home_advantage": home_advantage,
        "k_factor": k_factor,
        "source": "own_approved_historical_archive_only",
    }


def predict_winner(
    archive_rows: Iterable[dict[str, Any]],
    home_team_key: str,
    away_team_key: str,
    *,
    as_of_date: str,
    game_type: int = 2,
    min_games: int = DEFAULT_MIN_GAMES,
    min_team_games: int = DEFAULT_MIN_TEAM_GAMES,
) -> dict[str, Any]:
    """Return winner probabilities only when own-archive sample requirements pass."""
    home, away = str(home_team_key or "").strip().upper(), str(away_team_key or "").strip().upper()
    if not home or not away or home == away:
        raise ValueError("Se requieren dos claves canónicas de equipos diferentes.")
    if min_games < 1 or min_team_games < 1:
        raise ValueError("Los mínimos de muestra deben ser mayores que cero.")

    model = build_elo_ratings(archive_rows, game_type=game_type, as_of_date=as_of_date)
    home_n = model["games_played_by_team"].get(home, 0)
    away_n = model["games_played_by_team"].get(away, 0)
    result = {
        "success": True,
        "model_version": MODEL_VERSION,
        "status": "INSUFFICIENT_HISTORICAL_SAMPLE",
        "market": "moneyline_winner_including_overtime",
        "home_team_key": home,
        "away_team_key": away,
        "as_of_date_exclusive": as_of_date,
        "game_type": game_type,
        "historical_games_used": model["games_used"],
        "home_team_games_used": home_n,
        "away_team_games_used": away_n,
        "minimum_total_games": min_games,
        "minimum_games_per_team": min_team_games,
        "source": model["source"],
        "probabilities": None,
        "ratings": {"home": model["ratings"].get(home), "away": model["ratings"].get(away)},
    }
    if model["games_used"] < min_games or min(home_n, away_n) < min_team_games:
        result["message"] = "El archivo propio todavía no alcanza la muestra mínima; no se publica un porcentaje."
        return result

    p_home = _expected_home(
        model["ratings"].get(home, DEFAULT_INITIAL_RATING),
        model["ratings"].get(away, DEFAULT_INITIAL_RATING),
        model["home_advantage"],
    )
    result["status"] = "RESEARCH_PROJECTION"
    result["probabilities"] = {"home_win": round(p_home * 100, 2), "away_win": round((1 - p_home) * 100, 2)}
    result["message"] = "Probabilidad Elo experimental basada solo en partidos elegibles anteriores a la fecha de corte."
    return result
