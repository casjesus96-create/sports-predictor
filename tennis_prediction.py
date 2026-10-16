"""Official baseline engine for pre-match tennis Elo projections.

The engine is intentionally deterministic and side-effect free. It accepts
historical rows from a caller, excludes every match on or after the exclusive
cutoff date, freezes ratings within each date batch, and never trains on the
target match result. Persistence and production activation are handled by the
API/repository layer, not this module.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable

MODEL_VERSION = "TENNIS-ELO-1.0.0"
INITIAL_RATING = 1500.0
DEFAULT_K_FACTOR = 32.0
MIN_K_FACTOR = 4.0
MAX_K_FACTOR = 64.0


def _parse_date(value: str | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("La fecha de corte debe usar formato YYYY-MM-DD.") from exc


def normalize_player_name(value: Any) -> str:
    """Normalize a name consistently for rating lookup; do not fuzzy-match."""
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_name = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_name.casefold()).strip()


def elo_probability(rating_a: float, rating_b: float) -> float:
    """Probability that player A wins, with bounded exponent for stability."""
    if not math.isfinite(rating_a) or not math.isfinite(rating_b):
        raise ValueError("Los ratings Elo deben ser números finitos.")
    exponent = max(-10.0, min(10.0, (rating_b - rating_a) / 400.0))
    return 1.0 / (1.0 + 10.0 ** exponent)


def _match_date(row: dict[str, Any]) -> date | None:
    raw = str(row.get("tourney_date") or "").strip()
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def _valid_match(row: dict[str, Any]) -> bool:
    winner = normalize_player_name(row.get("winner_name"))
    loser = normalize_player_name(row.get("loser_name"))
    score = str(row.get("score") or "").casefold().strip()
    if not winner or not loser or winner == loser:
        return False
    if "walkover" in score or "w/o" in score or score in {"wo", "def", "abandoned"}:
        return False
    return True


def build_pre_match_ratings(
    rows: Iterable[dict[str, Any]],
    cutoff_date: str | date,
    k_factor: float = DEFAULT_K_FACTOR,
) -> dict[str, Any]:
    """Build ratings only from valid matches strictly before cutoff_date.

    All matches on the same tournament date are processed as a batch. Ratings
    are frozen for each batch and updates are applied only after the batch.
    """
    cutoff = _parse_date(cutoff_date)
    if not math.isfinite(k_factor) or not MIN_K_FACTOR <= k_factor <= MAX_K_FACTOR:
        raise ValueError("k_factor debe estar entre 4 y 64.")

    by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    excluded = {"invalid_date": 0, "on_or_after_cutoff": 0, "invalid_match": 0}
    for row in rows:
        played_on = _match_date(row)
        if played_on is None:
            excluded["invalid_date"] += 1
            continue
        if played_on >= cutoff:
            excluded["on_or_after_cutoff"] += 1
            continue
        if not _valid_match(row):
            excluded["invalid_match"] += 1
            continue
        by_date[played_on].append(row)

    ratings: dict[str, float] = {}
    matches_used = 0
    for played_on in sorted(by_date):
        day_rows = sorted(
            by_date[played_on],
            key=lambda row: (
                normalize_player_name(row.get("winner_name")),
                normalize_player_name(row.get("loser_name")),
                str(row.get("score") or ""),
            ),
        )
        deltas: dict[str, float] = defaultdict(float)
        for row in day_rows:
            winner = normalize_player_name(row.get("winner_name"))
            loser = normalize_player_name(row.get("loser_name"))
            winner_rating = ratings.get(winner, INITIAL_RATING)
            loser_rating = ratings.get(loser, INITIAL_RATING)
            expected_winner = elo_probability(winner_rating, loser_rating)
            deltas[winner] += k_factor * (1.0 - expected_winner)
            deltas[loser] -= k_factor * (1.0 - expected_winner)
        for player, delta in deltas.items():
            ratings[player] = ratings.get(player, INITIAL_RATING) + delta
        matches_used += len(day_rows)

    return {
        "ratings": ratings,
        "cutoff_date_exclusive": cutoff.isoformat(),
        "matches_used": matches_used,
        "players_rated": len(ratings),
        "excluded": excluded,
        "k_factor": float(k_factor),
        "model_version": MODEL_VERSION,
    }


def project_match(
    player1_name: str,
    player2_name: str,
    rating_state: dict[str, Any],
) -> dict[str, Any]:
    """Return the official general-Elo projection for player1 vs player2."""
    p1_key = normalize_player_name(player1_name)
    p2_key = normalize_player_name(player2_name)
    if not p1_key or not p2_key:
        raise ValueError("Se requieren los nombres de ambos jugadores.")
    if p1_key == p2_key:
        raise ValueError("Los jugadores deben ser distintos.")

    ratings = rating_state.get("ratings") or {}
    p1_rating = float(ratings.get(p1_key, INITIAL_RATING))
    p2_rating = float(ratings.get(p2_key, INITIAL_RATING))
    p1_probability = elo_probability(p1_rating, p2_rating)
    p2_probability = 1.0 - p1_probability
    return {
        "success": True,
        "model": "Tennis Elo general",
        "model_version": MODEL_VERSION,
        "model_status": "baseline_official_candidate",
        "player1": {
            "name": player1_name,
            "rating": round(p1_rating, 2),
            "win_probability": round(p1_probability, 6),
        },
        "player2": {
            "name": player2_name,
            "rating": round(p2_rating, 2),
            "win_probability": round(p2_probability, 6),
        },
        "cutoff_date_exclusive": rating_state.get("cutoff_date_exclusive"),
        "historical_matches_used": int(rating_state.get("matches_used", 0)),
        "rated_players": int(rating_state.get("players_rated", 0)),
        "k_factor": rating_state.get("k_factor", DEFAULT_K_FACTOR),
        "limitations": [
            "La probabilidad usa Elo general; no incorpora todavía superficie ni variables contextuales.",
            "Un jugador sin historial disponible recibe el rating inicial de 1500.",
            "La proyección es una estimación experimental hasta completar persistencia y validación fuera de muestra.",
        ],
    }
