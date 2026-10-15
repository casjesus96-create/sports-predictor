"""Leakage-conscious chronological Elo backtest for historical tennis results.

Research-only evaluation. This module does not expose a live prediction model.
The source provides tournament dates rather than exact match timestamps, so all
matches assigned the same date are forecast with ratings frozen before that
date and ratings are updated only after the entire date batch is evaluated.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from tennis_history import HistoricalDataError, _match_date, load_year

SUPPORTED_LEAGUES = {"ATP", "WTA"}
DEFAULT_INITIAL_RATING = 1500.0
DEFAULT_K_FACTOR = 32.0
MAX_EVALUATION_DAYS = 366


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Las fechas deben usar el formato YYYY-MM-DD.") from exc


def _elo_probability(rating_a: float, rating_b: float) -> float:
    exponent = max(-10.0, min(10.0, (rating_b - rating_a) / 400.0))
    return 1.0 / (1.0 + 10.0 ** exponent)


def _valid_match(row: dict[str, str]) -> bool:
    winner = str(row.get("winner_name") or "").strip()
    loser = str(row.get("loser_name") or "").strip()
    if not winner or not loser or winner.casefold() == loser.casefold():
        return False
    score = str(row.get("score") or "").casefold()
    if "walkover" in score or "w/o" in score or score.strip() in {"wo", "def"}:
        return False
    return True


def _elo_update(ratings: dict[str, float], winner: str, loser: str, k_factor: float) -> None:
    winner_rating = ratings.get(winner, DEFAULT_INITIAL_RATING)
    loser_rating = ratings.get(loser, DEFAULT_INITIAL_RATING)
    expected_winner = _elo_probability(winner_rating, loser_rating)
    ratings[winner] = winner_rating + k_factor * (1.0 - expected_winner)
    ratings[loser] = loser_rating + k_factor * (0.0 - (1.0 - expected_winner))


def evaluate_rows(
    rows: Iterable[dict[str, str]],
    start_date: str | date,
    end_date: str | date,
    k_factor: float = DEFAULT_K_FACTOR,
) -> dict[str, Any]:
    """Evaluate a chronological Elo baseline on rows; rows may be unordered."""
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if end < start:
        raise ValueError("end_date debe ser igual o posterior a start_date.")
    if (end - start).days + 1 > MAX_EVALUATION_DAYS:
        raise ValueError("El periodo de evaluación no puede superar 366 días.")
    if not math.isfinite(k_factor) or not 4.0 <= k_factor <= 64.0:
        raise ValueError("k_factor debe estar entre 4 y 64.")

    by_date: dict[date, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        rows_seen += 1
        played_on = _match_date(row)
        if not played_on:
            rows_without_valid_date += 1
            continue
        if played_on > end:
            rows_after_end_date += 1
            continue
        score = str(row.get("score") or "").casefold().strip()
        if "walkover" in score or "w/o" in score or score in {"wo", "def"}:
            matches_excluded_walkover += 1
            continue
        if not _valid_match(row):
            matches_excluded_invalid += 1
            continue
        by_date[played_on].append(row)

    ratings: dict[str, float] = {}
    evaluation_count = 0
    correct_score = 0.0
    brier_sum = 0.0
    log_loss_sum = 0.0
    evaluated_days = set()
    rating_snapshot_examples: list[dict[str, Any]] = []
    rows_seen = 0
    rows_after_end_date = 0
    rows_without_valid_date = 0
    matches_excluded_walkover = 0
    matches_excluded_invalid = 0
    matches_used_for_rating_updates = 0

    # Crucial: freeze ratings for the whole date batch. Since source dates are
    # tournament dates (not exact match timestamps), same-date results cannot
    # influence another prediction assigned to that date.
    for match_date in sorted(by_date):
        day_matches = sorted(
            by_date[match_date],
            key=lambda row: (
                str(row.get("winner_name") or "").casefold(),
                str(row.get("loser_name") or "").casefold(),
                str(row.get("score") or ""),
            ),
        )
        forecasts = []
        for row in day_matches:
            matches_used_for_rating_updates += 1
            winner = str(row["winner_name"]).strip()
            loser = str(row["loser_name"]).strip()
            p_winner = _elo_probability(
                ratings.get(winner, DEFAULT_INITIAL_RATING),
                ratings.get(loser, DEFAULT_INITIAL_RATING),
            )
            if start <= match_date <= end:
                forecasts.append((winner, loser, p_winner, row))
        for winner, loser, probability, row in forecasts:
            evaluation_count += 1
            # Equal Elo ratings imply no directional edge. Give a tied
            # forecast half credit instead of incorrectly counting it as a win.
            if probability > 0.5:
                correct_score += 1.0
            elif math.isclose(probability, 0.5, abs_tol=1e-12):
                correct_score += 0.5
            brier_sum += (probability - 1.0) ** 2
            clipped = min(1.0 - 1e-15, max(1e-15, probability))
            log_loss_sum -= math.log(clipped)
            evaluated_days.add(match_date.isoformat())
            if len(rating_snapshot_examples) < 5:
                rating_snapshot_examples.append({
                    "event_date": match_date.isoformat(),
                    "winner": winner,
                    "loser": loser,
                    "pre_match_probability_of_recorded_winner": round(probability, 6),
                })
        # Compute every update from the same frozen pre-date ratings, then
        # apply summed deltas. This avoids arbitrary row-order effects when a
        # player appears more than once in a date batch.
        deltas: dict[str, float] = defaultdict(float)
        for row in day_matches:
            winner = str(row["winner_name"]).strip()
            loser = str(row["loser_name"]).strip()
            winner_rating = ratings.get(winner, DEFAULT_INITIAL_RATING)
            loser_rating = ratings.get(loser, DEFAULT_INITIAL_RATING)
            expected_winner = _elo_probability(winner_rating, loser_rating)
            deltas[winner] += k_factor * (1.0 - expected_winner)
            deltas[loser] -= k_factor * (1.0 - expected_winner)
        for player, delta in deltas.items():
            ratings[player] = ratings.get(player, DEFAULT_INITIAL_RATING) + delta

    if evaluation_count == 0:
        accuracy = brier_score = log_loss = None
        benchmark = {
            "name": "50_50_coin_flip",
            "accuracy": 0.5,
            "brier_score": 0.25,
            "log_loss": round(math.log(2.0), 6),
            "elo_brier_improvement": None,
            "elo_log_loss_improvement": None,
        }
    else:
        accuracy = round(correct_score / evaluation_count, 4)
        brier_score = round(brier_sum / evaluation_count, 6)
        log_loss = round(log_loss_sum / evaluation_count, 6)
        benchmark = {
            "name": "50_50_coin_flip",
            "accuracy": 0.5,
            "brier_score": 0.25,
            "log_loss": round(math.log(2.0), 6),
            # Positive values mean Elo has lower (better) probabilistic loss.
            "elo_brier_improvement": round(0.25 - brier_score, 6),
            "elo_log_loss_improvement": round(math.log(2.0) - log_loss, 6),
        }

    return {
        "success": True,
        "model_status": "research_only",
        "model": "tennis-elo-baseline-research",
        "league": None,
        "evaluation": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "matches_evaluated": evaluation_count,
            "dates_evaluated": len(evaluated_days),
            "accuracy": accuracy,
            "brier_score": brier_score,
            "log_loss": log_loss,
            "benchmark": benchmark,
        },
        "data_quality": {
            "historical_rows_seen": rows_seen,
            "valid_matches_available_through_end_date": sum(len(items) for items in by_date.values()),
            "matches_used_for_rating_updates": matches_used_for_rating_updates,
            "matches_excluded_walkover": matches_excluded_walkover,
            "matches_excluded_invalid": matches_excluded_invalid,
            "rows_without_valid_date": rows_without_valid_date,
            "rows_after_end_date_ignored": rows_after_end_date,
            "evaluation_matches": evaluation_count,
        },
        "configuration": {
            "initial_rating": DEFAULT_INITIAL_RATING,
            "k_factor": k_factor,
            "same_date_batching": True,
            "source_date_precision": "tournament date only; not exact match timestamp",
        },
        "examples": rating_snapshot_examples,
        "limitations": [
            "Research baseline only; it does not produce production predictions.",
            "Tournament dates are used because exact match timestamps are not supplied consistently.",
            "Ratings update after each date batch, never between matches sharing a date.",
            "The evaluation period must be historical and must not include future matches.",
            "Dataset licensing must be reviewed before commercial use.",
        ],
    }


def run_elo_backtest(
    league: str,
    start_date: str | date,
    end_date: str | date,
    warmup_years: int = 3,
    k_factor: float = DEFAULT_K_FACTOR,
) -> dict[str, Any]:
    league = str(league or "").strip().upper()
    if league not in SUPPORTED_LEAGUES:
        raise ValueError("league debe ser ATP o WTA.")
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    today = datetime.now(timezone.utc).date()
    if end >= today:
        raise ValueError("end_date debe ser anterior al día actual para evaluar solo partidos históricos.")
    if end < start:
        raise ValueError("end_date debe ser igual o posterior a start_date.")
    if (end - start).days + 1 > MAX_EVALUATION_DAYS:
        raise ValueError("El periodo de evaluación no puede superar 366 días.")
    if not 1 <= int(warmup_years) <= 10:
        raise ValueError("warmup_years debe estar entre 1 y 10.")
    if not math.isfinite(k_factor) or not 4.0 <= k_factor <= 64.0:
        raise ValueError("k_factor debe estar entre 4 y 64.")

    first_year = max(1968, start.year - int(warmup_years))
    rows: list[dict[str, str]] = []
    years_loaded = []
    for year in range(first_year, end.year + 1):
        annual_rows = load_year(league, year)
        if annual_rows:
            years_loaded.append(year)
            rows.extend(annual_rows)
    result = evaluate_rows(rows, start, end, k_factor)
    result["league"] = league
    result["configuration"]["warmup_years_requested"] = int(warmup_years)
    result["configuration"]["annual_files_loaded"] = years_loaded
    result["data_quality"] = {
        "historical_rows_loaded": len(rows),
        "annual_files_available": years_loaded,
        "source": f"Jeff Sackmann {league} historical match CSVs",
        "source_url": (
            "https://github.com/JeffSackmann/tennis_atp"
            if league == "ATP" else "https://github.com/JeffSackmann/tennis_wta"
        ),
    }
    return result
