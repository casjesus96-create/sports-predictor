"""Research-only comparison of general Elo and surface-aware Elo for tennis.

Predictions are evaluated chronologically with all matches on a tournament date
forecast from ratings frozen before that date. Surface Elo falls back to general
Elo unless both players have enough prior matches on that surface.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Iterable

from tennis_backtest import (
    DEFAULT_INITIAL_RATING,
    DEFAULT_K_FACTOR,
    MAX_EVALUATION_DAYS,
    SUPPORTED_LEAGUES,
    _elo_probability,
    _match_date,
    _parse_date,
    _valid_match,
)
from tennis_history import HistoricalDataError, load_year

SURFACES = ("Hard", "Clay", "Grass")
MIN_SURFACE_MATCHES_DEFAULT = 10


def _normalize_surface(value: Any) -> str | None:
    normalized = str(value or "").strip().casefold()
    aliases = {
        "hard": "Hard",
        "hard court": "Hard",
        "clay": "Clay",
        "clay court": "Clay",
        "grass": "Grass",
        "grass court": "Grass",
    }
    return aliases.get(normalized)


def _metric_summary(rows: list[tuple[float, bool]]) -> dict[str, Any]:
    count = len(rows)
    if not count:
        return {
            "matches_evaluated": 0,
            "accuracy": None,
            "brier_score": None,
            "log_loss": None,
        }
    # A row is (P(recorded winner wins), outcome_is_recorded_winner), which is
    # always true for the archive's winner/loser format. Keep explicit outcomes
    # so this helper also remains correct for synthetic unit tests.
    brier = sum((p - (1.0 if outcome else 0.0)) ** 2 for p, outcome in rows) / count
    loss = sum(-math.log(min(1 - 1e-15, max(1e-15, p if outcome else 1 - p))) for p, outcome in rows) / count
    accuracy_score = sum(
        1.0 if (p >= 0.5) == outcome else 0.0
        for p, outcome in rows
        if not math.isclose(p, 0.5, abs_tol=1e-12)
    )
    ties = sum(math.isclose(p, 0.5, abs_tol=1e-12) for p, _ in rows)
    return {
        "matches_evaluated": count,
        "accuracy": round((accuracy_score + 0.5 * ties) / count, 4),
        "brier_score": round(brier, 6),
        "log_loss": round(loss, 6),
    }


def evaluate_surface_rows(
    rows: Iterable[dict[str, str]],
    start_date: str | date,
    end_date: str | date,
    k_factor: float = DEFAULT_K_FACTOR,
    min_surface_matches: int = MIN_SURFACE_MATCHES_DEFAULT,
) -> dict[str, Any]:
    """Compare general Elo with surface Elo; input rows may be unordered."""
    start, end = _parse_date(start_date), _parse_date(end_date)
    if end < start:
        raise ValueError("end_date debe ser igual o posterior a start_date.")
    if (end - start).days + 1 > MAX_EVALUATION_DAYS:
        raise ValueError("El periodo de evaluación no puede superar 366 días.")
    if not math.isfinite(k_factor) or not 4.0 <= k_factor <= 64.0:
        raise ValueError("k_factor debe estar entre 4 y 64.")
    if isinstance(min_surface_matches, bool) or not 1 <= int(min_surface_matches) <= 100:
        raise ValueError("min_surface_matches debe estar entre 1 y 100.")

    by_date: dict[date, list[dict[str, str]]] = defaultdict(list)
    rows_seen = rows_without_date = excluded_invalid = excluded_walkover = 0
    ignored_after_end = 0
    for row in rows:
        rows_seen += 1
        played_on = _match_date(row)
        if played_on is None:
            rows_without_date += 1
            continue
        if played_on > end:
            ignored_after_end += 1
            continue
        score = str(row.get("score") or "").casefold().strip()
        if "walkover" in score or "w/o" in score or score in {"wo", "def"}:
            excluded_walkover += 1
            continue
        if not _valid_match(row):
            excluded_invalid += 1
            continue
        by_date[played_on].append(row)

    general_ratings: dict[str, float] = {}
    surface_ratings: dict[str, dict[str, float]] = {surface: {} for surface in SURFACES}
    surface_counts: dict[str, dict[str, int]] = {surface: defaultdict(int) for surface in SURFACES}
    general_eval: list[tuple[float, bool]] = []
    surface_eval: list[tuple[float, bool]] = []
    monthly: dict[str, dict[str, list[tuple[float, bool]]]] = defaultdict(
        lambda: {"general": [], "surface": []}
    )
    surface_eval_counts: dict[str, int] = defaultdict(int)
    surface_fallback_counts: dict[str, int] = defaultdict(int)
    surface_unavailable_counts: dict[str, int] = defaultdict(int)
    valid_update_matches = 0

    for played_on in sorted(by_date):
        day_rows = sorted(
            by_date[played_on],
            key=lambda r: (
                str(r.get("winner_name") or "").casefold(),
                str(r.get("loser_name") or "").casefold(),
                str(r.get("score") or ""),
                str(r.get("surface") or "").casefold(),
            ),
        )
        forecasts = []
        # Forecast the complete date batch from ratings frozen before that day.
        for row in day_rows:
            winner = str(row["winner_name"]).strip()
            loser = str(row["loser_name"]).strip()
            p_general = _elo_probability(
                general_ratings.get(winner, DEFAULT_INITIAL_RATING),
                general_ratings.get(loser, DEFAULT_INITIAL_RATING),
            )
            surface = _normalize_surface(row.get("surface"))
            if surface:
                enough_history = (
                    surface_counts[surface].get(winner, 0) >= int(min_surface_matches)
                    and surface_counts[surface].get(loser, 0) >= int(min_surface_matches)
                )
                if enough_history:
                    p_surface = _elo_probability(
                        surface_ratings[surface].get(winner, DEFAULT_INITIAL_RATING),
                        surface_ratings[surface].get(loser, DEFAULT_INITIAL_RATING),
                    )
                    surface_eval_counts[surface] += int(start <= played_on <= end)
                else:
                    p_surface = p_general
                    surface_fallback_counts[surface] += int(start <= played_on <= end)
            else:
                p_surface = p_general
                surface_unavailable_counts["unknown"] += int(start <= played_on <= end)

            if start <= played_on <= end:
                general_eval.append((p_general, True))
                surface_eval.append((p_surface, True))
                bucket = monthly[played_on.strftime("%Y-%m")]
                bucket["general"].append((p_general, True))
                bucket["surface"].append((p_surface, True))
            forecasts.append((row, surface))

        # Updates are based on pre-date ratings; aggregate deltas to remove
        # row-order dependence when a player appears more than once that day.
        general_deltas: dict[str, float] = defaultdict(float)
        surface_deltas: dict[str, dict[str, float]] = {
            surface: defaultdict(float) for surface in SURFACES
        }
        for row, surface in forecasts:
            winner = str(row["winner_name"]).strip()
            loser = str(row["loser_name"]).strip()
            wr = general_ratings.get(winner, DEFAULT_INITIAL_RATING)
            lr = general_ratings.get(loser, DEFAULT_INITIAL_RATING)
            expected = _elo_probability(wr, lr)
            general_deltas[winner] += k_factor * (1.0 - expected)
            general_deltas[loser] -= k_factor * (1.0 - expected)
            valid_update_matches += 1

            if surface:
                swr = surface_ratings[surface].get(winner, DEFAULT_INITIAL_RATING)
                slr = surface_ratings[surface].get(loser, DEFAULT_INITIAL_RATING)
                sexpected = _elo_probability(swr, slr)
                surface_deltas[surface][winner] += k_factor * (1.0 - sexpected)
                surface_deltas[surface][loser] -= k_factor * (1.0 - sexpected)
                surface_counts[surface][winner] += 1
                surface_counts[surface][loser] += 1

        for player, delta in general_deltas.items():
            general_ratings[player] = general_ratings.get(player, DEFAULT_INITIAL_RATING) + delta
        for surface in SURFACES:
            for player, delta in surface_deltas[surface].items():
                surface_ratings[surface][player] = (
                    surface_ratings[surface].get(player, DEFAULT_INITIAL_RATING) + delta
                )

    monthly_breakdown = []
    cursor = start.replace(day=1)
    while cursor <= end:
        key = cursor.strftime("%Y-%m")
        monthly_breakdown.append({
            "month": key,
            "general_elo": _metric_summary(monthly[key]["general"]),
            "surface_elo_with_fallback": _metric_summary(monthly[key]["surface"]),
        })
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)

    general_summary = _metric_summary(general_eval)
    surface_summary = _metric_summary(surface_eval)
    surface_coverage = {
        surface: {
            "evaluated_with_surface_ratings": surface_eval_counts[surface],
            "fallback_to_general_elo": surface_fallback_counts[surface],
            "minimum_prior_matches_per_player": int(min_surface_matches),
        }
        for surface in SURFACES
    }
    surface_coverage["unknown"] = {
        "evaluated_with_surface_ratings": 0,
        "fallback_to_general_elo": surface_unavailable_counts["unknown"],
        "reason": "Missing or unsupported surface value; used general Elo.",
    }
    return {
        "success": True,
        "model_status": "research_only",
        "model": "tennis-surface-elo-comparison-research",
        "evaluation": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "general_elo": general_summary,
            "surface_elo_with_fallback": surface_summary,
            "surface_elo_brier_improvement_vs_general": (
                round(general_summary["brier_score"] - surface_summary["brier_score"], 6)
                if general_summary["brier_score"] is not None and surface_summary["brier_score"] is not None
                else None
            ),
            "surface_elo_log_loss_improvement_vs_general": (
                round(general_summary["log_loss"] - surface_summary["log_loss"], 6)
                if general_summary["log_loss"] is not None and surface_summary["log_loss"] is not None
                else None
            ),
            "monthly_breakdown": monthly_breakdown,
        },
        "surface_coverage": surface_coverage,
        "data_quality": {
            "historical_rows_seen": rows_seen,
            "valid_matches_used_for_rating_updates": valid_update_matches,
            "matches_excluded_walkover": excluded_walkover,
            "matches_excluded_invalid": excluded_invalid,
            "rows_without_valid_date": rows_without_date,
            "rows_after_end_date_ignored": ignored_after_end,
            "matches_evaluated": len(general_eval),
        },
        "configuration": {
            "initial_rating": DEFAULT_INITIAL_RATING,
            "k_factor": k_factor,
            "minimum_surface_matches_per_player": int(min_surface_matches),
            "same_date_batching": True,
            "source_date_precision": "tournament date only; not exact match timestamp",
            "surface_rating_updates": "valid historical matches with recognized surface",
            "surface_fallback": "general Elo until both players meet the per-surface history threshold",
        },
        "limitations": [
            "Research-only comparison; no live predictions or production model changes.",
            "Same-date matches are forecast before any result from that date updates ratings.",
            "Surface-specific ratings start at 1500 and are not shrunk toward general ratings.",
            "The source's tournament date is not an exact match timestamp.",
            "Historical dataset licensing must be reviewed before commercial use.",
        ],
    }


def run_surface_elo_backtest(
    league: str,
    start_date: str | date,
    end_date: str | date,
    warmup_years: int = 3,
    k_factor: float = DEFAULT_K_FACTOR,
    min_surface_matches: int = MIN_SURFACE_MATCHES_DEFAULT,
) -> dict[str, Any]:
    league = str(league or "").strip().upper()
    if league not in SUPPORTED_LEAGUES:
        raise ValueError("league debe ser ATP o WTA.")
    start, end = _parse_date(start_date), _parse_date(end_date)
    if end >= datetime.now(timezone.utc).date():
        raise ValueError("end_date debe ser anterior al día actual para evaluar solo partidos históricos.")
    if end < start:
        raise ValueError("end_date debe ser igual o posterior a start_date.")
    if not 1 <= int(warmup_years) <= 10:
        raise ValueError("warmup_years debe estar entre 1 y 10.")
    first_year = max(1968, start.year - int(warmup_years))
    rows: list[dict[str, str]] = []
    years_loaded = []
    for year in range(first_year, end.year + 1):
        annual = load_year(league, year)
        if annual:
            years_loaded.append(year)
            rows.extend(annual)
    if not rows:
        raise HistoricalDataError(
            f"No se cargaron datos históricos {league} desde el archivo anual. "
            "Verifica la disponibilidad de la fuente y vuelve a intentarlo."
        )
    result = evaluate_surface_rows(rows, start, end, k_factor, min_surface_matches)
    result["league"] = league
    result["configuration"]["warmup_years_requested"] = int(warmup_years)
    result["configuration"]["annual_files_loaded"] = years_loaded
    result["data_quality"]["historical_rows_loaded"] = len(rows)
    return result
