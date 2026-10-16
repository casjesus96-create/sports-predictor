"""Chronological research validation for tennis surface Elo.

Runs separate calendar-year evaluations with prior-season warmup, calibration
bins, per-surface metrics, and raw surface-label diagnostics. Research-only.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from tennis_backtest import (
    DEFAULT_INITIAL_RATING,
    DEFAULT_K_FACTOR,
    SUPPORTED_LEAGUES,
    _elo_probability,
    _match_date,
    _valid_match,
)
from tennis_history import HistoricalDataError, load_year
from tennis_surface_backtest import BLEND_WEIGHTS, SURFACES, _normalize_surface


METHODS = ("general_elo", "blend_25", "blend_50", "blend_75")


def _summary(rows: list[tuple[float, int]]) -> dict[str, Any]:
    """Metrics for probability of a consistently oriented player A winning."""
    if not rows:
        return {"matches_evaluated": 0, "accuracy": None, "brier_score": None, "log_loss": None}
    n = len(rows)
    accuracy = sum(1.0 if (p > 0.5 and y == 1) or (p < 0.5 and y == 0) else 0.5 if math.isclose(p, 0.5, abs_tol=1e-12) else 0.0 for p, y in rows) / n
    brier = sum((p - y) ** 2 for p, y in rows) / n
    loss = sum(-math.log(max(1e-15, min(1 - 1e-15, p if y else 1 - p))) for p, y in rows) / n
    return {
        "matches_evaluated": n,
        "accuracy": round(accuracy, 4),
        "brier_score": round(brier, 6),
        "log_loss": round(loss, 6),
    }


def _calibration(rows: list[tuple[float, int]], bins: int = 10) -> list[dict[str, Any]]:
    """Reliability bins; player orientation is alphabetical, not winner-only."""
    output = []
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        selected = [(p, y) for p, y in rows if lower <= p < upper or (index == bins - 1 and p == 1.0)]
        output.append({
            "bin": f"{lower:.1f}-{upper:.1f}",
            "matches": len(selected),
            "mean_predicted_probability": round(sum(p for p, _ in selected) / len(selected), 4) if selected else None,
            "observed_win_rate": round(sum(y for _, y in selected) / len(selected), 4) if selected else None,
        })
    return output


def _evaluate_year(rows: list[dict[str, str]], year: int, k_factor: float, min_surface_matches: int, end_override: date | None = None) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    default_end = date(year, 12, 31) if year < today.year else min(date(year, 12, 31), today - timedelta(days=1))
    start, end = date(year, 1, 1), min(default_end, end_override) if end_override else default_end
    by_date: dict[date, list[dict[str, str]]] = defaultdict(list)
    raw_surface_counts: dict[str, int] = defaultdict(int)
    normalized_surface_counts: dict[str, int] = defaultdict(int)
    excluded = {"walkover": 0, "invalid": 0, "missing_date": 0}
    for row in rows:
        played = _match_date(row)
        if played is None:
            excluded["missing_date"] += 1
            continue
        if played > end:
            continue
        raw = str(row.get("surface") or "")
        normalized_surface = _normalize_surface(raw)
        if start <= played <= end:
            # Preserve the source label verbatim for diagnostics; normalize only
            # the separate normalized counter used to inspect data consistency.
            raw_surface_counts[raw if raw.strip() else "<blank>"] += 1
            normalized_surface_counts[normalized_surface or "<unknown>"] += 1
        score = str(row.get("score") or "").casefold().strip()
        if "walkover" in score or "w/o" in score or score in {"wo", "def"}:
            excluded["walkover"] += int(start <= played <= end)
            continue
        if not _valid_match(row):
            excluded["invalid"] += int(start <= played <= end)
            continue
        by_date[played].append(row)

    general: dict[str, float] = {}
    surface_ratings: dict[str, dict[str, float]] = {s: {} for s in SURFACES}
    surface_counts: dict[str, dict[str, int]] = {s: defaultdict(int) for s in SURFACES}
    predictions: dict[str, list[tuple[float, int]]] = {name: [] for name in METHODS}
    by_surface: dict[str, dict[str, list[tuple[float, int]]]] = {
        s: {name: [] for name in METHODS} for s in (*SURFACES, "unknown")
    }
    surface_coverage = {s: {"with_surface_ratings": 0, "fallback_to_general": 0} for s in SURFACES}
    surface_coverage["unknown"] = {"with_surface_ratings": 0, "fallback_to_general": 0}

    for played in sorted(by_date):
        day_rows = sorted(by_date[played], key=lambda r: (
            str(r.get("winner_name") or "").casefold(),
            str(r.get("loser_name") or "").casefold(),
            str(r.get("score") or ""),
        ))
        forecasts = []
        for row in day_rows:
            winner, loser = str(row["winner_name"]).strip(), str(row["loser_name"]).strip()
            p_winner_general = _elo_probability(general.get(winner, DEFAULT_INITIAL_RATING), general.get(loser, DEFAULT_INITIAL_RATING))
            surface = _normalize_surface(row.get("surface"))
            if surface and surface_counts[surface].get(winner, 0) >= min_surface_matches and surface_counts[surface].get(loser, 0) >= min_surface_matches:
                p_winner_surface = _elo_probability(surface_ratings[surface].get(winner, DEFAULT_INITIAL_RATING), surface_ratings[surface].get(loser, DEFAULT_INITIAL_RATING))
                used_surface = True
            else:
                p_winner_surface = p_winner_general
                used_surface = False

            # Consistent alphabetical orientation makes calibration meaningful.
            player_a, player_b = sorted((winner, loser), key=str.casefold)
            winner_is_a = winner.casefold() == player_a.casefold()
            outcome_a = int(winner_is_a)
            p_general_a = p_winner_general if winner_is_a else 1.0 - p_winner_general
            p_surface_a = p_winner_surface if winner_is_a else 1.0 - p_winner_surface
            probs = {"general_elo": p_general_a}
            for weight in BLEND_WEIGHTS:
                blended_winner = (1 - weight) * p_winner_general + weight * p_winner_surface
                probs[f"blend_{int(weight * 100)}"] = blended_winner if winner_is_a else 1.0 - blended_winner

            if start <= played <= end:
                bucket = surface if surface else "unknown"
                surface_coverage[bucket]["with_surface_ratings" if used_surface else "fallback_to_general"] += 1
                for method, probability in probs.items():
                    predictions[method].append((probability, outcome_a))
                    by_surface[bucket][method].append((probability, outcome_a))
            forecasts.append((row, surface))

        # Aggregate same-day updates from frozen ratings to avoid row-order leakage.
        general_delta: dict[str, float] = defaultdict(float)
        surface_delta: dict[str, dict[str, float]] = {s: defaultdict(float) for s in SURFACES}
        for row, surface in forecasts:
            winner, loser = str(row["winner_name"]).strip(), str(row["loser_name"]).strip()
            rw, rl = general.get(winner, DEFAULT_INITIAL_RATING), general.get(loser, DEFAULT_INITIAL_RATING)
            expected = _elo_probability(rw, rl)
            general_delta[winner] += k_factor * (1 - expected)
            general_delta[loser] -= k_factor * (1 - expected)
            if surface:
                sw = surface_ratings[surface].get(winner, DEFAULT_INITIAL_RATING)
                sl = surface_ratings[surface].get(loser, DEFAULT_INITIAL_RATING)
                sexpected = _elo_probability(sw, sl)
                surface_delta[surface][winner] += k_factor * (1 - sexpected)
                surface_delta[surface][loser] -= k_factor * (1 - sexpected)
                surface_counts[surface][winner] += 1
                surface_counts[surface][loser] += 1
        for player, delta in general_delta.items():
            general[player] = general.get(player, DEFAULT_INITIAL_RATING) + delta
        for surface in SURFACES:
            for player, delta in surface_delta[surface].items():
                surface_ratings[surface][player] = surface_ratings[surface].get(player, DEFAULT_INITIAL_RATING) + delta

    return {
        "year": year,
        "evaluation_end_date": end.isoformat(),
        "matches_evaluated": len(predictions["general_elo"]),
        "metrics": {name: _summary(values) for name, values in predictions.items()},
        "calibration": {
            name: _calibration(values)
            for name, values in predictions.items()
        },
        "metrics_by_surface": {
            surface: {name: _summary(values) for name, values in methods.items()}
            for surface, methods in by_surface.items()
        },
        "surface_coverage": surface_coverage,
        "raw_surface_labels_in_evaluation_window": dict(sorted(raw_surface_counts.items(), key=lambda item: item[0].casefold())),
        "normalized_surface_labels_in_evaluation_window": dict(sorted(normalized_surface_counts.items(), key=lambda item: item[0].casefold())),
        "data_quality": {"excluded_walkover": excluded["walkover"], "excluded_invalid": excluded["invalid"], "rows_without_valid_date": excluded["missing_date"]},
    }


def run_chronological_surface_validation(
    league: str,
    validation_years: tuple[int, ...] = (2023, 2024),
    reference_year: int = 2025,
    holdout_year: int = 2026,
    warmup_years: int = 3,
    k_factor: float = DEFAULT_K_FACTOR,
    min_surface_matches: int = 10,
) -> dict[str, Any]:
    """Validate predeclared seasons, report a reference season, and reserve a holdout."""
    league = str(league or "").strip().upper()
    if league not in SUPPORTED_LEAGUES:
        raise ValueError("league debe ser ATP o WTA.")
    if not validation_years or len(set(validation_years)) != len(validation_years):
        raise ValueError("validation_years debe contener años únicos.")
    years = list(validation_years) + [reference_year, holdout_year]
    if any(isinstance(y, bool) or not 2000 <= int(y) <= datetime.now(timezone.utc).year for y in years):
        raise ValueError("Año de validación fuera del rango permitido.")
    if len(set(years)) != len(years):
        raise ValueError("Los años de validación, referencia y holdout deben ser distintos.")
    if max(validation_years) >= reference_year or reference_year >= holdout_year:
        raise ValueError("Los años deben estar ordenados: validación, referencia y holdout.")
    if not 1 <= int(warmup_years) <= 10:
        raise ValueError("warmup_years debe estar entre 1 y 10.")
    if not math.isfinite(k_factor) or not 4 <= k_factor <= 64:
        raise ValueError("k_factor debe estar entre 4 y 64.")
    if isinstance(min_surface_matches, bool) or not 1 <= int(min_surface_matches) <= 100:
        raise ValueError("min_surface_matches debe estar entre 1 y 100.")

    today = datetime.now(timezone.utc).date()
    if holdout_year > today.year:
        raise ValueError("holdout_year no puede estar en el futuro.")
    first_year = max(1968, min(years) - int(warmup_years))
    last_year = min(max(years), today.year)
    loaded: dict[int, tuple[dict[str, str], ...]] = {}
    for year in range(first_year, last_year + 1):
        loaded[year] = load_year(league, year)
    if not any(loaded.values()):
        raise HistoricalDataError(f"No se cargaron históricos {league} para la validación cronológica.")

    windows = []
    for year in years:
        if year == today.year:
            # Current season is evaluated only through yesterday.
            target_end = today - timedelta(days=1)
            target_rows = [row for y in range(max(1968, year - warmup_years), year + 1) for row in loaded.get(y, ())]
            windows.append(_evaluate_year(target_rows, year, k_factor, int(min_surface_matches), end_override=target_end))
            windows[-1]["role"] = "holdout_partial_year" if year == holdout_year else "current_year_partial"
        else:
            target_rows = [row for y in range(max(1968, year - warmup_years), year + 1) for row in loaded.get(y, ())]
            item = _evaluate_year(target_rows, year, k_factor, int(min_surface_matches))
            if year in validation_years:
                item["role"] = "validation"
            elif year == reference_year:
                item["role"] = "reference_seen_before"
            elif year == holdout_year:
                item["role"] = "holdout_full_year"
            else:
                item["role"] = "unassigned"
            windows.append(item)

    return {
        "success": True,
        "model_status": "research_only",
        "model": "tennis-surface-elo-chronological-validation",
        "league": league,
        "protocol": {
            "validation_years": list(validation_years),
            "reference_year": reference_year,
            "holdout_year": holdout_year,
            "warmup_years": int(warmup_years),
            "k_factor": k_factor,
            "minimum_surface_matches_per_player": int(min_surface_matches),
            "same_date_batching": True,
            "calibration_orientation": "Alphabetical player orientation; observed outcome is whether player A won.",
            "as_of_date_utc": today.isoformat(),
            "holdout_cutoff_exclusive": today.isoformat() if holdout_year == today.year else None,
            "holdout_evaluation_end_date": (today - timedelta(days=1)).isoformat() if holdout_year == today.year else None,
            "holdout_status": (
                "Current year through yesterday; not used to select weights."
                if holdout_year == today.year
                else "Completed historical year; interpret as a holdout only if it was not inspected or used to tune weights."
            ),
            "official_model_changed": False,
        },
        "windows": windows,
        "limitations": [
            "Research-only; does not alter live predictions or the official model.",
            "2025 was already examined in prior research and is therefore reference-only, not an untouched holdout.",
            "A current-year holdout is partial and must be interpreted with seasonality in mind; a completed-year holdout is only untouched if it was not inspected or used to tune weights.",
            "Tournament date is not an exact match timestamp; same-date forecasts use frozen pre-date ratings.",
            "Calibration bins are descriptive and should be read with their match counts.",
            "Historical dataset licensing must be reviewed before commercial use.",
        ],
        "annual_files_loaded": [year for year, rows in loaded.items() if rows],
    }
