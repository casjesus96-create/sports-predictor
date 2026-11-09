"""Read-only comparison of official football forecasts against historical baselines."""
from __future__ import annotations

import math
import unicodedata
from bisect import bisect_left
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from football_archive import normalize_team_key
from football_model import MODEL_VERSION

OUTCOMES = ("HOME", "DRAW", "AWAY")
MIN_COMPETITION_HISTORY = 50
MIN_TEAM_VENUE_HISTORY = 5
TEAM_VENUE_WINDOW = 10


def _date(value: Any) -> date | None:
    try:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _kickoff(value: Any, competition_timezone: str) -> tuple[datetime, date] | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        local = parsed.astimezone(ZoneInfo(competition_timezone))
        return parsed.astimezone(timezone.utc), local.date()
    except (TypeError, ValueError, KeyError):
        return None


def _probabilities(row: dict[str, Any]) -> dict[str, float] | None:
    values = {}
    for key, field in (("HOME", "home_probability"), ("DRAW", "draw_probability"), ("AWAY", "away_probability")):
        try:
            value = float(row.get(field))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value < 0 or value > 1:
            return None
        values[key] = value
    total = sum(values.values())
    if total <= 0 or abs(total - 1.0) > 0.03:
        return None
    return {key: value / total for key, value in values.items()}


def _actual(row: dict[str, Any]) -> tuple[str, int, int] | None:
    try:
        home = int(row.get("actual_home_score"))
        away = int(row.get("actual_away_score"))
    except (TypeError, ValueError):
        return None
    if home < 0 or away < 0:
        return None
    stored = str(row.get("actual_outcome") or "").strip().upper()
    outcome = stored if stored in OUTCOMES else "HOME" if home > away else "AWAY" if home < away else "DRAW"
    return outcome, home, away


def _market_probability(payload: Any, market: str) -> float | None:
    if not isinstance(payload, dict):
        return None
    goals = payload.get("goal_markets") or {}
    if market == "btts_yes":
        value = (((goals.get("both_teams_to_score") or {}).get("yes") or {}).get("probability"))
    else:
        value = (((goals.get("total_goals") or {}).get("over_2_5") or {}).get("probability"))
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and 0 <= parsed <= 1 else None


def _normalize_archive(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = []
    for row in rows:
        day = _date(row.get("match_date"))
        try:
            home_score, away_score = int(row.get("home_score")), int(row.get("away_score"))
        except (TypeError, ValueError):
            continue
        if day is None or home_score < 0 or away_score < 0:
            continue
        home_key = str(row.get("home_team_key") or normalize_team_key(row.get("home_team") or ""))
        away_key = str(row.get("away_team_key") or normalize_team_key(row.get("away_team") or ""))
        if not home_key or not away_key or home_key == away_key:
            continue
        valid.append({
            "day": day, "home_key": home_key, "away_key": away_key,
            "home_score": home_score, "away_score": away_score,
            "outcome": "HOME" if home_score > away_score else "AWAY" if home_score < away_score else "DRAW",
            "btts": home_score > 0 and away_score > 0,
            "over_2_5": home_score + away_score >= 3,
        })
    return sorted(valid, key=lambda row: row["day"])


def _smoothed_outcome_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    counts = {key: 1 for key in OUTCOMES}
    for row in rows:
        counts[row["outcome"]] += 1
    denominator = len(rows) + len(OUTCOMES)
    return {key: counts[key] / denominator for key in OUTCOMES}


def _smoothed_binary(rows: list[dict[str, Any]], key: str) -> float:
    positives = sum(bool(row[key]) for row in rows)
    return (positives + 1) / (len(rows) + 2)


def _league_baseline(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(history) < MIN_COMPETITION_HISTORY:
        return None
    return {
        "one_x_two": _smoothed_outcome_rates(history),
        "btts_yes": _smoothed_binary(history, "btts"),
        "over_2_5": _smoothed_binary(history, "over_2_5"),
        "history_sample": len(history),
    }


def _team_venue_rows(history: list[dict[str, Any]], team_key: str, venue: str) -> list[dict[str, Any]]:
    if venue == "home":
        selected = [row for row in history if row["home_key"] == team_key]
    else:
        selected = [row for row in history if row["away_key"] == team_key]
    return selected[-TEAM_VENUE_WINDOW:]


def _team_rates(rows: list[dict[str, Any]], venue: str) -> dict[str, float] | None:
    if len(rows) < MIN_TEAM_VENUE_HISTORY:
        return None
    counts = {"win": 1, "draw": 1, "loss": 1}
    for row in rows:
        if row["outcome"] == "DRAW":
            counts["draw"] += 1
        elif (venue == "home" and row["outcome"] == "HOME") or (venue == "away" and row["outcome"] == "AWAY"):
            counts["win"] += 1
        else:
            counts["loss"] += 1
    denominator = len(rows) + 3
    return {
        "win": counts["win"] / denominator,
        "draw": counts["draw"] / denominator,
        "loss": counts["loss"] / denominator,
        "btts_yes": _smoothed_binary(rows, "btts"),
        "over_2_5": _smoothed_binary(rows, "over_2_5"),
        "sample_size": len(rows),
    }


def _recent_form_baseline(
    history: list[dict[str, Any]], home_key: str, away_key: str
) -> dict[str, Any] | None:
    home_rows = _team_venue_rows(history, home_key, "home")
    away_rows = _team_venue_rows(history, away_key, "away")
    home = _team_rates(home_rows, "home")
    away = _team_rates(away_rows, "away")
    if home is None or away is None:
        return None
    probabilities = {
        "HOME": (home["win"] + away["loss"]) / 2,
        "DRAW": (home["draw"] + away["draw"]) / 2,
        "AWAY": (home["loss"] + away["win"]) / 2,
    }
    total = sum(probabilities.values())
    if total <= 0:
        return None
    return {
        "one_x_two": {key: value / total for key, value in probabilities.items()},
        "btts_yes": (home["btts_yes"] + away["btts_yes"]) / 2,
        "over_2_5": (home["over_2_5"] + away["over_2_5"]) / 2,
        "home_team_history": home["sample_size"],
        "away_team_history": away["sample_size"],
    }


def _multiclass_metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"sample_size": 0, "accuracy": None, "brier_score": None, "log_loss": None}
    correct = 0
    brier_total = 0.0
    log_total = 0.0
    for row in rows:
        probs = row[key]
        actual = row["actual"]
        predicted = max(OUTCOMES, key=lambda outcome: probs[outcome])
        correct += predicted == actual
        brier_total += sum((probs[outcome] - (1.0 if actual == outcome else 0.0)) ** 2 for outcome in OUTCOMES)
        log_total += -math.log(max(probs[actual], 1e-15))
    return {
        "sample_size": n,
        "accuracy": round(correct / n, 5),
        "brier_score": round(brier_total / n, 5),
        "log_loss": round(log_total / n, 5),
    }


def _binary_metrics(rows: list[dict[str, Any]], key: str, actual_key: str) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"sample_size": 0, "accuracy": None, "brier_score": None, "log_loss": None}
    correct = 0
    brier_total = 0.0
    log_total = 0.0
    for row in rows:
        probability = row[key]
        actual = bool(row[actual_key])
        correct += (probability >= 0.5) == actual
        y = 1.0 if actual else 0.0
        brier_total += (probability - y) ** 2
        log_total += -(y * math.log(max(probability, 1e-15)) + (1 - y) * math.log(max(1 - probability, 1e-15)))
    return {
        "sample_size": n,
        "accuracy": round(correct / n, 5),
        "brier_score": round(brier_total / n, 5),
        "log_loss": round(log_total / n, 5),
    }


def _deltas(official: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float | None]:
    result = {}
    for key in ("accuracy", "brier_score", "log_loss"):
        left, right = official.get(key), baseline.get(key)
        result[key] = round(left - right, 5) if isinstance(left, (int, float)) and isinstance(right, (int, float)) else None
    return result


def _comparison(rows: list[dict[str, Any]], kind: str, actual_key: str | None = None) -> dict[str, Any]:
    metric = _multiclass_metrics if kind == "one_x_two" else None
    if kind == "one_x_two":
        official = metric(rows, "official")
        league = metric(rows, "league")
        recent = metric(rows, "recent")
    else:
        official = _binary_metrics(rows, "official", actual_key)
        league = _binary_metrics(rows, "league", actual_key)
        recent = _binary_metrics(rows, "recent", actual_key)
    return {
        "sample_size": len(rows),
        "official_model": official,
        "league_frequency_baseline": league,
        "recent_form_baseline": recent,
        "delta_official_minus_league": _deltas(official, league),
        "delta_official_minus_recent": _deltas(official, recent),
        "interpretation": "En accuracy, delta positivo favorece al modelo; en Brier y Log Loss, delta negativo favorece al modelo.",
    }


def _prepare_targets(
    snapshots: list[dict[str, Any]], competition_timezone: str
) -> tuple[list[dict[str, Any]], int]:
    valid = []
    excluded = 0
    for row in snapshots:
        kickoff = _kickoff(row.get("kickoff_at"), competition_timezone)
        probs = _probabilities(row)
        actual = _actual(row)
        if (
            kickoff is None or probs is None or actual is None
            or row.get("result_status") != "SETTLED"
            or row.get("model_version") != MODEL_VERSION
        ):
            excluded += 1
            continue
        stamp, day = kickoff
        home_key = normalize_team_key(row.get("home_team") or "")
        away_key = normalize_team_key(row.get("away_team") or "")
        if not home_key or not away_key or home_key == away_key:
            excluded += 1
            continue
        outcome, home_score, away_score = actual
        payload = row.get("prediction_payload") if isinstance(row.get("prediction_payload"), dict) else {}
        valid.append({
            "sort_stamp": stamp, "day": day, "match_id": row.get("provider_match_id"),
            "home_key": home_key, "away_key": away_key,
            "actual": outcome, "actual_btts": home_score > 0 and away_score > 0,
            "actual_over_2_5": home_score + away_score >= 3,
            "official": probs,
            "official_btts_yes": _market_probability(payload, "btts_yes"),
            "official_over_2_5": _market_probability(payload, "over_2_5"),
        })
    valid.sort(key=lambda row: (row["sort_stamp"], str(row["match_id"] or "")))
    return valid, excluded


def _evaluate_slice(
    targets: list[dict[str, Any]],
    archive_rows: list[dict[str, Any]],
    archive_dates: list[date],
    *,
    frozen_cutoff: date | None = None,
) -> dict[str, Any]:
    paired = []
    league_eligible = 0
    recent_eligible = 0
    for target in targets:
        cutoff = frozen_cutoff if frozen_cutoff is not None else target["day"]
        history_end = bisect_left(archive_dates, cutoff)
        history = archive_rows[:history_end]
        league = _league_baseline(history)
        recent = _recent_form_baseline(history, target["home_key"], target["away_key"])
        if league is not None:
            league_eligible += 1
        if recent is not None:
            recent_eligible += 1
        if league is None or recent is None:
            continue
        paired.append({
            **target,
            "league": league["one_x_two"],
            "recent": recent["one_x_two"],
            "league_btts_yes": league["btts_yes"],
            "recent_btts_yes": recent["btts_yes"],
            "league_over_2_5": league["over_2_5"],
            "recent_over_2_5": recent["over_2_5"],
        })

    one_x_two = _comparison(paired, "one_x_two")
    market_rows = {}
    for market, actual_key in (("btts_yes", "actual_btts"), ("over_2_5", "actual_over_2_5")):
        market_sample = [
            {
                "official": row[f"official_{market}"],
                "league": row[f"league_{market}"],
                "recent": row[f"recent_{market}"],
                actual_key: row[actual_key],
            }
            for row in paired if row.get(f"official_{market}") is not None
        ]
        market_rows[market] = _comparison(market_sample, "binary", actual_key)
    return {
        "official_valid_targets": len(targets),
        "league_baseline_eligible_targets": league_eligible,
        "recent_form_baseline_eligible_targets": recent_eligible,
        "paired_1x2_sample_size": len(paired),
        "one_x_two": one_x_two,
        "markets": market_rows,
    }


def build_baseline_comparison(
    snapshots: list[dict[str, Any]],
    archive: list[dict[str, Any]],
    competition: str,
    competition_timezone: str,
    *,
    snapshot_truncated: bool = False,
    archive_truncated: bool = False,
) -> dict[str, Any]:
    """Compare immutable official snapshots with two strictly pre-match baselines."""
    targets, excluded = _prepare_targets(snapshots, competition_timezone)
    history = _normalize_archive(archive)
    history_dates = [row["day"] for row in history]

    split = max(1, int(len(targets) * 0.8)) if targets else 0
    while 0 < split < len(targets) and targets[split - 1]["day"] == targets[split]["day"]:
        split += 1
    development = targets[:split]
    holdout = targets[split:]
    holdout_start = holdout[0]["day"] if holdout else None

    development_report = _evaluate_slice(development, history, history_dates)
    holdout_report = _evaluate_slice(
        holdout, history, history_dates, frozen_cutoff=holdout_start
    ) if holdout_start else {
        "official_valid_targets": 0, "league_baseline_eligible_targets": 0,
        "recent_form_baseline_eligible_targets": 0, "paired_1x2_sample_size": 0,
        "one_x_two": _comparison([], "one_x_two"),
        "markets": {
            "btts_yes": _comparison([], "binary", "actual_btts"),
            "over_2_5": _comparison([], "binary", "actual_over_2_5"),
        },
    }

    return {
        "success": True,
        "protocol": "chronological_frozen_holdout_baselines_v1",
        "competition": competition,
        "model_version": MODEL_VERSION,
        "snapshot_sample_size": len(targets),
        "excluded_invalid_snapshots": excluded,
        "archive_history_rows": len(history),
        "history_truncated": archive_truncated,
        "snapshots_truncated": snapshot_truncated,
        "split": {
            "development_share": 0.8,
            "holdout_share": 0.2,
            "development_matches": len(development),
            "holdout_matches": len(holdout),
            "holdout_start_local_date": holdout_start.isoformat() if holdout_start else None,
            "rule": (
                "Corte cronológico por fecha local de la competición; ninguna jornada/fecha se divide. "
                "El holdout usa una línea base congelada con archivo anterior al primer día de holdout; "
                "ningún resultado del holdout alimenta sus propias líneas base."
            ),
        },
        "minimums": {
            "competition_history_matches": MIN_COMPETITION_HISTORY,
            "team_home_or_away_history_matches": MIN_TEAM_VENUE_HISTORY,
            "team_venue_window": TEAM_VENUE_WINDOW,
            "smoothing": "Laplace/Dirichlet +1; probabilidades estimadas solo con resultados anteriores al corte.",
        },
        "development": development_report,
        "holdout": holdout_report,
        "data_scope": (
            "Solo snapshots oficiales SETTLED de FOOTBALL-POISSON-0.5.0 y resultados del archivo propio. "
            "La frecuencia de liga usa todo el historial anterior; la forma reciente usa hasta 10 partidos "
            "de local del local y 10 de visitante del visitante. Los partidos del mismo día se excluyen."
        ),
        "read_only": True,
        "model_changed": False,
        "snapshots_written": 0,
        "provider_calls": 0,
        "automatic_recalibration": False,
        "limitations": [
            "La comparación no mide rentabilidad ni incorpora cuotas de mercado.",
            "La forma reciente es una referencia descriptiva simple, no un modelo entrenado.",
            "El holdout queda congelado antes de su primer día; no consume resultados del propio holdout.",
            "Si la cobertura histórica o la identidad de equipos no alcanza los mínimos, los partidos se excluyen de la muestra emparejada.",
            "Los resultados de desarrollo sirven para diagnóstico; el holdout es la evaluación final y no debe usarse para ajustar esta versión.",
        ],
    }
