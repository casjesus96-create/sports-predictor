"""Read-only post-match learning diagnostics for official football snapshots."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from football_model import MODEL_VERSION
from repository import get_supabase_client

router = APIRouter(prefix="/api/v1/football/learning", tags=["Football post-match learning"])
OUTCOMES = ("HOME", "DRAW", "AWAY")


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _actual_outcome(row: dict[str, Any]) -> str | None:
    stored = str(row.get("actual_outcome") or "").strip().upper()
    if stored in OUTCOMES:
        return stored
    home, away = _number(row.get("actual_home_score")), _number(row.get("actual_away_score"))
    if home is None or away is None:
        return None
    return "HOME" if home > away else "AWAY" if home < away else "DRAW"


def _probabilities(row: dict[str, Any]) -> dict[str, float] | None:
    raw = {
        "HOME": _number(row.get("home_probability")),
        "DRAW": _number(row.get("draw_probability")),
        "AWAY": _number(row.get("away_probability")),
    }
    if any(value is None or value < 0 or value > 1 for value in raw.values()):
        return None
    total = sum(raw.values())
    if total <= 0 or abs(total - 1.0) > 0.03:
        return None
    return {key: float(value) / total for key, value in raw.items()}


def _market_probability(payload: dict, market: str) -> float | None:
    goals = payload.get("goal_markets") or {}
    if market == "btts":
        value = (((goals.get("both_teams_to_score") or {}).get("yes") or {}).get("probability"))
    else:
        value = (((goals.get("total_goals") or {}).get("over_2_5") or {}).get("probability"))
    parsed = _number(value)
    return parsed if parsed is not None and 0 <= parsed <= 1 else None


def _wilson_interval(successes: int, sample_size: int, z: float = 1.959963984540054) -> dict[str, float] | None:
    """Return a two-sided 95% Wilson score interval for a binomial rate."""
    if sample_size <= 0:
        return None
    proportion = successes / sample_size
    z_squared = z * z
    denominator = 1 + z_squared / sample_size
    center = (proportion + z_squared / (2 * sample_size)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / sample_size
            + z_squared / (4 * sample_size * sample_size)
        )
        / denominator
    )
    return {
        "lower": round(max(0.0, center - margin), 4),
        "upper": round(min(1.0, center + margin), 4),
    }


def _binary_market_metrics(items: list[dict[str, Any]], probability_key: str, actual_key: str) -> dict[str, Any]:
    usable = []
    for item in items:
        probability, actual = item.get(probability_key), item.get(actual_key)
        if probability is None or not isinstance(actual, bool) or not math.isfinite(probability) or not 0 <= probability <= 1:
            continue
        usable.append((float(probability), float(actual)))
    bins = []
    for lower, upper in ((0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.000001)):
        subset = [(p, y) for p, y in usable if lower <= p < upper]
        successes = int(sum(y for _, y in subset))
        bins.append({"range": f"{int(lower*100)}–{int(min(1,upper)*100)}%", "sample_size": len(subset),
                     "mean_probability": round(sum(p for p, _ in subset)/len(subset), 4) if subset else None,
                     "observed_rate": round(successes/len(subset), 4) if subset else None,
                     "observed_rate_ci_95": _wilson_interval(successes, len(subset))})
    n = len(usable)
    return {"sample_size": n,
            "brier_score": round(sum((p-y)**2 for p,y in usable)/n, 5) if n else None,
            "log_loss": round(sum(-(y*math.log(max(p,1e-15))+(1-y)*math.log(max(1-p,1e-15))) for p,y in usable)/n, 5) if n else None,
            "calibration_bins": bins}



SEGMENT_MINIMUM_SAMPLE = 30


def _football_season(kickoff_at: Any, competition_code: str) -> str | None:
    """Assign a fixture to a July-to-June season using the competition's local date."""
    try:
        from football_archive import COMPETITIONS
        config = COMPETITIONS.get(str(competition_code or "").upper())
        if not config:
            return None
        parsed = datetime.fromisoformat(str(kickoff_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        local_date = parsed.astimezone(ZoneInfo(config["timezone"])).date()
        start_year = local_date.year if local_date.month >= 7 else local_date.year - 1
        return f"{start_year}/{str(start_year + 1)[-2:]}"
    except (TypeError, ValueError, KeyError):
        return None


def _segmented_calibration_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Return metrics only when the relevant segment has a defensible minimum N."""
    n = len(items)
    eligible = n >= SEGMENT_MINIMUM_SAMPLE
    outcomes = {}
    for key, probability_key, actual_key in (
        ("home", "home_p", "actual_home"),
        ("draw", "draw_p", "actual_draw"),
        ("away", "away_p", "actual_away"),
    ):
        metric = _binary_market_metrics(items, probability_key, actual_key)
        outcomes[key] = {
            "sample_size": metric["sample_size"],
            "eligible": metric["sample_size"] >= SEGMENT_MINIMUM_SAMPLE,
            "metrics": metric if metric["sample_size"] >= SEGMENT_MINIMUM_SAMPLE else None,
        }

    markets = {}
    for key, probability_key, actual_key in (
        ("btts_yes", "btts_p", "actual_btts"),
        ("over_2_5", "over25_p", "actual_over25"),
    ):
        metric = _binary_market_metrics(items, probability_key, actual_key)
        markets[key] = {
            "sample_size": metric["sample_size"],
            "eligible": metric["sample_size"] >= SEGMENT_MINIMUM_SAMPLE,
            "metrics": metric if metric["sample_size"] >= SEGMENT_MINIMUM_SAMPLE else None,
        }

    multiclass = None
    if eligible:
        multiclass = {
            "accuracy": round(sum(item["correct"] for item in items) / n, 5),
            "brier_score": round(sum(item["brier"] for item in items) / n, 5),
            "log_loss": round(sum(item["log_loss"] for item in items) / n, 5),
        }
    return {
        "sample_size": n,
        "minimum_sample": SEGMENT_MINIMUM_SAMPLE,
        "eligible": eligible,
        "metrics": multiclass,
        "outcomes": outcomes,
        "markets": markets,
        "status": "EVALUABLE" if eligible else "INSUFFICIENT_SAMPLE",
    }


def _build_segmented_calibration(valid: list[dict[str, Any]]) -> dict[str, Any]:
    by_competition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_season: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    excluded_missing_season = 0
    for item in valid:
        row = item["row"]
        competition = str(row.get("competition_code") or "").strip().upper()
        season = _football_season(row.get("kickoff_at"), competition)
        if not competition or not season:
            excluded_missing_season += 1
            continue
        by_competition[competition].append(item)
        by_season[(competition, season)].append(item)

    return {
        "minimum_sample": SEGMENT_MINIMUM_SAMPLE,
        "season_definition": "Temporada local julio–junio; la fecha de inicio se calcula con la zona horaria oficial de cada competición.",
        "by_competition": [
            {"competition": code, **_segmented_calibration_summary(items)}
            for code, items in sorted(by_competition.items())
        ],
        "by_season": [
            {"competition": code, "season": season, **_segmented_calibration_summary(items)}
            for (code, season), items in sorted(by_season.items())
        ],
        "excluded_missing_competition_or_season": excluded_missing_season,
        "read_only": True,
        "model_changed": False,
    }


ERROR_DIAGNOSTIC_MINIMUM_SAMPLE = 30


def _build_error_diagnostics(valid: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe classification and goal residuals without changing the model."""
    matrix = {
        predicted: {
            actual: sum(1 for item in valid if item["predicted"] == predicted and item["actual"] == actual)
            for actual in OUTCOMES
        }
        for predicted in OUTCOMES
    }
    goal_metrics = {}
    dimensions = (
        ("home_goals", "expected_home", "home_score"),
        ("away_goals", "expected_away", "away_score"),
        ("total_goals", "expected_total", None),
    )
    for key, expected_key, actual_key in dimensions:
        pairs = []
        for item in valid:
            expected = item.get(expected_key)
            actual = item["home_score"] + item["away_score"] if actual_key is None else item[actual_key]
            if expected is not None and math.isfinite(expected):
                pairs.append((float(expected), float(actual)))
        n = len(pairs)
        eligible = n >= ERROR_DIAGNOSTIC_MINIMUM_SAMPLE
        residuals = [actual - expected for expected, actual in pairs]
        goal_metrics[key] = {
            "sample_size": n,
            "minimum_sample": ERROR_DIAGNOSTIC_MINIMUM_SAMPLE,
            "eligible": eligible,
            "bias_actual_minus_expected": round(sum(residuals) / n, 4) if eligible else None,
            "mae": round(sum(abs(value) for value in residuals) / n, 4) if eligible else None,
            "rmse": round(math.sqrt(sum(value * value for value in residuals) / n), 4) if eligible else None,
        }
    return {
        "confusion_matrix": {
            "predicted_rows_actual_columns": matrix,
            "sample_size": len(valid),
            "labels": {"HOME": "Victoria local", "DRAW": "Empate", "AWAY": "Victoria visitante"},
        },
        "goal_residuals": goal_metrics,
        "minimum_goal_sample": ERROR_DIAGNOSTIC_MINIMUM_SAMPLE,
        "interpretation": "Sesgo = goles reales menos esperados; positivo indica subestimación y negativo sobreestimación. Métricas de goles solo se publican con N suficiente.",
        "read_only": True,
        "model_changed": False,
    }



def _build_segmented_error_diagnostics(valid: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe error patterns by competition and local season, with minimum-N safeguards."""
    by_competition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_season: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    excluded_missing_competition_or_season = 0
    for item in valid:
        row = item["row"]
        competition = str(row.get("competition_code") or "").strip().upper()
        season = _football_season(row.get("kickoff_at"), competition)
        if not competition or not season:
            excluded_missing_competition_or_season += 1
            continue
        by_competition[competition].append(item)
        by_season[(competition, season)].append(item)

    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        diagnostics = _build_error_diagnostics(items)
        return {
            "sample_size": len(items),
            "eligible": len(items) >= ERROR_DIAGNOSTIC_MINIMUM_SAMPLE,
            "confusion_matrix": diagnostics["confusion_matrix"]["predicted_rows_actual_columns"],
            "goal_residuals": diagnostics["goal_residuals"],
        }

    return {
        "minimum_sample": ERROR_DIAGNOSTIC_MINIMUM_SAMPLE,
        "season_definition": "Temporada local julio–junio según la zona horaria oficial de cada competición.",
        "by_competition": [
            {"competition": code, **summarize(items)}
            for code, items in sorted(by_competition.items())
        ],
        "by_season": [
            {"competition": code, "season": season, **summarize(items)}
            for (code, season), items in sorted(by_season.items())
        ],
        "excluded_missing_competition_or_season": excluded_missing_competition_or_season,
        "read_only": True,
        "model_changed": False,
    }


TEMPORAL_ERROR_WINDOW_MINIMUM_SAMPLE = 30


def _build_temporal_error_stability(valid: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare two non-overlapping chronological windows without splitting local match dates."""
    from football_archive import COMPETITIONS

    by_competition: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    excluded = 0
    for item in valid:
        row = item["row"]
        competition = str(row.get("competition_code") or "").strip().upper()
        config = COMPETITIONS.get(competition)
        kickoff = row.get("kickoff_at")
        try:
            parsed = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
            if not config or parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("unknown competition or timezone")
            local_date = parsed.astimezone(ZoneInfo(config["timezone"])).date().isoformat()
        except (TypeError, ValueError, KeyError):
            excluded += 1
            continue
        by_competition[competition][local_date].append(item)

    segments = []
    for competition, dates in sorted(by_competition.items()):
        ordered_dates = sorted(dates)
        total = sum(len(dates[date]) for date in ordered_dates)
        candidates = []
        left_count = 0
        for index, date in enumerate(ordered_dates[:-1], start=1):
            left_count += len(dates[date])
            right_count = total - left_count
            if left_count >= TEMPORAL_ERROR_WINDOW_MINIMUM_SAMPLE and right_count >= TEMPORAL_ERROR_WINDOW_MINIMUM_SAMPLE:
                candidates.append((abs(left_count - right_count), index, left_count, right_count))
        if not candidates:
            segments.append({
                "competition": competition,
                "sample_size": total,
                "eligible": False,
                "minimum_per_window": TEMPORAL_ERROR_WINDOW_MINIMUM_SAMPLE,
                "windows": [],
                "reason": "Se requieren al menos 30 partidos en cada una de dos ventanas cronológicas y fechas locales distintas.",
            })
            continue

        _, split_index, left_count, right_count = min(candidates)
        split_date = ordered_dates[split_index]
        windows = (
            ("earlier", ordered_dates[:split_index]),
            ("later", ordered_dates[split_index:]),
        )
        window_results = []
        for label, window_dates in windows:
            items = [item for date in window_dates for item in dates[date]]
            diagnostic = _build_error_diagnostics(items)
            window_results.append({
                "period": label,
                "sample_size": len(items),
                "start_local_date": window_dates[0],
                "end_local_date": window_dates[-1],
                "confusion_matrix": diagnostic["confusion_matrix"]["predicted_rows_actual_columns"],
                "goal_residuals": diagnostic["goal_residuals"],
            })
        segments.append({
            "competition": competition,
            "sample_size": total,
            "eligible": True,
            "minimum_per_window": TEMPORAL_ERROR_WINDOW_MINIMUM_SAMPLE,
            "split_before_local_date": split_date,
            "windows": window_results,
        })

    return {
        "minimum_per_window": TEMPORAL_ERROR_WINDOW_MINIMUM_SAMPLE,
        "date_cluster": "Todos los partidos de una misma fecha local permanecen en la misma ventana.",
        "by_competition": segments,
        "excluded_missing_competition_or_kickoff": excluded,
        "read_only": True,
        "model_changed": False,
    }

def build_postmatch_learning_report(rows: list[dict[str, Any]], competition: str | None = None) -> dict[str, Any]:
    """Score immutable settled official snapshots and expose descriptive error patterns."""
    valid = []
    excluded = 0
    for row in rows:
        probs = _probabilities(row)
        actual = _actual_outcome(row)
        home_score, away_score = _number(row.get("actual_home_score")), _number(row.get("actual_away_score"))
        if probs is None or actual is None or home_score is None or away_score is None:
            excluded += 1
            continue
        predicted = max(OUTCOMES, key=lambda key: probs[key])
        confidence = probs[predicted]
        log_loss = -math.log(max(1e-15, probs[actual]))
        brier = sum((probs[key] - (1.0 if actual == key else 0.0)) ** 2 for key in OUTCOMES)
        payload = row.get("prediction_payload") if isinstance(row.get("prediction_payload"), dict) else {}
        expected = row.get("expected_goals") if isinstance(row.get("expected_goals"), dict) else {}
        if not expected:
            expected = payload.get("expected_goals") if isinstance(payload.get("expected_goals"), dict) else {}
        expected_home = _number(expected.get("home"))
        expected_away = _number(expected.get("away"))
        expected_total = _number(expected.get("total"))
        if expected_total is None and expected_home is not None and expected_away is not None:
            expected_total = expected_home + expected_away
        btts_p = _market_probability(payload, "btts")
        over25_p = _market_probability(payload, "over25")
        actual_btts = home_score > 0 and away_score > 0
        actual_over25 = home_score + away_score >= 3
        valid.append({
            "row": row, "probabilities": probs, "actual": actual, "predicted": predicted,
            "confidence": confidence, "correct": predicted == actual,
            "log_loss": log_loss, "brier": brier,
            "home_score": home_score, "away_score": away_score,
            "expected_home": expected_home, "expected_away": expected_away,
            "expected_total": expected_total, "btts_p": btts_p, "over25_p": over25_p,
            "actual_btts": actual_btts, "actual_over25": actual_over25,
            "home_p": probs["HOME"], "draw_p": probs["DRAW"], "away_p": probs["AWAY"],
            "actual_home": actual == "HOME", "actual_draw": actual == "DRAW", "actual_away": actual == "AWAY",
        })

    n = len(valid)
    if not n:
        return {
            "success": True, "read_only": True, "model_version": MODEL_VERSION,
            "competition": competition, "sample_size": 0, "excluded_invalid_rows": excluded,
            "metrics": {"accuracy": None, "brier_score": None, "log_loss": None},
            "confidence_bands": [], "surprises": [],
            "market_calibration": {"btts_yes": _binary_market_metrics([], "btts_p", "actual_btts"),
                                   "over_2_5": _binary_market_metrics([], "over25_p", "actual_over25")},
            "outcome_calibration": {"sample_size": 0, "multiclass_brier_score": None, "multiclass_log_loss": None,
                                    "outcomes": {key.lower(): _binary_market_metrics([], f"{key.lower()}_p", f"actual_{key.lower()}") for key in OUTCOMES}},
            "segmented_calibration": _build_segmented_calibration([]),
            "error_diagnostics": _build_error_diagnostics([]),
            "segmented_error_diagnostics": _build_segmented_error_diagnostics([]),
            "temporal_error_stability": _build_temporal_error_stability([]),
            "signals": [
                "Todavía no hay suficientes snapshots oficiales liquidados y válidos para extraer patrones."
            ],
            "learning_policy": "Diagnóstico descriptivo; no modifica ni recalibra el modelo oficial.",
            "data_scope": "Solo snapshots oficiales inmutables FOOTBALL-POISSON-0.5.0 con resultado SETTLED; no usa resultados sin pronóstico prepartido.",
            "model_changed": False,
            "snapshots_written": 0,
            "provider_calls": 0,
        }

    accuracy = sum(item["correct"] for item in valid) / n
    brier = sum(item["brier"] for item in valid) / n
    log_loss = sum(item["log_loss"] for item in valid) / n
    thresholds = ((0.0, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 1.000001))
    bands = []
    for lower, upper in thresholds:
        subset = [item for item in valid if lower <= item["confidence"] < upper]
        bands.append({
            "range": f"{int(lower * 100)}–{int(min(1, upper) * 100)}%",
            "sample_size": len(subset),
            "accuracy": round(sum(item["correct"] for item in subset) / len(subset), 4) if subset else None,
            "mean_confidence": round(sum(item["confidence"] for item in subset) / len(subset), 4) if subset else None,
            "accuracy_ci_95": _wilson_interval(sum(item["correct"] for item in subset), len(subset)),
            "misses": sum(not item["correct"] for item in subset),
            "upsets": sum(not item["correct"] and item["confidence"] >= 0.50 for item in subset),
        })

    upset_rows = [item for item in valid if not item["correct"] and item["confidence"] >= 0.50]
    upset_rows.sort(key=lambda item: (item["log_loss"], item["confidence"]), reverse=True)
    surprises = []
    for item in upset_rows[:15]:
        row = item["row"]
        surprises.append({
            "match_id": row.get("provider_match_id"),
            "date": row.get("kickoff_at"),
            "home_team": row.get("home_team"),
            "away_team": row.get("away_team"),
            "score": f"{int(item['home_score'])}-{int(item['away_score'])}",
            "predicted_outcome": item["predicted"],
            "actual_outcome": item["actual"],
            "predicted_confidence": round(item["confidence"], 4),
            "actual_outcome_probability": round(item["probabilities"][item["actual"]], 4),
            "surprise_score": round(item["log_loss"], 4),
        })

    expected_rows = [item for item in valid if item["expected_total"] is not None]
    expected_goal_mae = (
        sum(abs(item["expected_total"] - item["home_score"] - item["away_score"]) for item in expected_rows)
        / len(expected_rows)
    ) if expected_rows else None
    btts_rows = [item for item in valid if item["btts_p"] is not None]
    over_rows = [item for item in valid if item["over25_p"] is not None]
    btts_report = _binary_market_metrics(valid, "btts_p", "actual_btts")
    over25_report = _binary_market_metrics(valid, "over25_p", "actual_over25")
    btts_brier = btts_report["brier_score"]
    over25_brier = over25_report["brier_score"]
    outcome_calibration = {
        "sample_size": n,
        "multiclass_brier_score": round(brier, 5),
        "multiclass_log_loss": round(log_loss, 5),
        "outcomes": {
            "home": _binary_market_metrics(valid, "home_p", "actual_home"),
            "draw": _binary_market_metrics(valid, "draw_p", "actual_draw"),
            "away": _binary_market_metrics(valid, "away_p", "actual_away"),
        },
    }

    signals = []
    high = [item for item in valid if item["confidence"] >= 0.70]
    if len(high) >= 10:
        high_accuracy = sum(item["correct"] for item in high) / len(high)
        if high_accuracy < sum(item["confidence"] for item in high) / len(high) - 0.10:
            signals.append("Sobreconfianza en selecciones de 70% o más: la tasa observada queda al menos 10 puntos por debajo de la confianza media.")
        else:
            signals.append("En la muestra de confianza alta no aparece una brecha de sobreconfianza superior a 10 puntos.")
    else:
        signals.append(f"Muestra insuficiente para diagnosticar confianza alta: {len(high)} partidos con 70% o más; se requieren 10.")
    if upset_rows:
        signals.append(f"Se detectaron {len(upset_rows)} sorpresas contra el resultado más probable; revisar sus fichas para buscar patrones repetidos, no causas aisladas.")
    else:
        signals.append("No hay sorpresas clasificadas con favorito de al menos 50% en esta muestra.")
    if expected_goal_mae is not None:
        signals.append(f"Error absoluto medio del total de goles esperados: {expected_goal_mae:.2f} goles en {len(expected_rows)} partidos.")
    if n < 100:
        signals.append("Muestra todavía pequeña: los patrones son exploratorios y no deben usarse para cambiar pesos.")
    return {
        "success": True, "read_only": True, "model_version": MODEL_VERSION,
        "competition": competition, "sample_size": n, "excluded_invalid_rows": excluded,
        "metrics": {
            "accuracy": round(accuracy, 4), "brier_score": round(brier, 5),
            "log_loss": round(log_loss, 5),
            "expected_total_goals_mae": round(expected_goal_mae, 4) if expected_goal_mae is not None else None,
            "expected_total_goals_sample": len(expected_rows),
            "btts_brier_score": round(btts_brier, 5) if btts_brier is not None else None,
            "btts_sample": len(btts_rows),
            "btts_log_loss": btts_report["log_loss"],
            "over_2_5_brier_score": round(over25_brier, 5) if over25_brier is not None else None,
            "over_2_5_sample": len(over_rows),
            "over_2_5_log_loss": over25_report["log_loss"],
            "upset_count": len(upset_rows),
        },
        "confidence_bands": bands, "surprises": surprises, "signals": signals,
        "market_calibration": {"btts_yes": btts_report, "over_2_5": over25_report},
        "outcome_calibration": outcome_calibration,
        "segmented_calibration": _build_segmented_calibration(valid),
        "error_diagnostics": _build_error_diagnostics(valid),
        "segmented_error_diagnostics": _build_segmented_error_diagnostics(valid),
        "temporal_error_stability": _build_temporal_error_stability(valid),
        "data_scope": "Solo snapshots oficiales inmutables FOOTBALL-POISSON-0.5.0 con resultado SETTLED; no usa resultados sin pronóstico prepartido.",
        "learning_policy": "Aprendizaje diagnóstico: mide errores, calibración, sorpresas y residuos de goles. No entrena, recalibra ni modifica probabilidades oficiales.",
        "model_changed": False, "snapshots_written": 0, "provider_calls": 0,
    }


def _team_key(value):
    return " ".join(str(value or "").casefold().split())


def _utc_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def build_match_learning_context(rows, competition, home_team, away_team, kickoff_at):
    """Read-only descriptive context based only on settled snapshots before kickoff."""
    valid = []
    for row in rows:
        stamp = _utc_datetime(row.get("kickoff_at"))
        target = _utc_datetime(kickoff_at)
        if stamp is None or target is None or stamp >= target:
            continue
        if row.get("result_status") != "SETTLED" or row.get("model_version") != MODEL_VERSION:
            continue
        probs = _probabilities(row)
        actual = _actual_outcome(row)
        hs, aws = _number(row.get("actual_home_score")), _number(row.get("actual_away_score"))
        if probs is None or actual is None or hs is None or aws is None:
            continue
        predicted = max(OUTCOMES, key=lambda key: probs[key])
        payload = row.get("prediction_payload") if isinstance(row.get("prediction_payload"), dict) else {}
        expected = row.get("expected_goals") if isinstance(row.get("expected_goals"), dict) else {}
        if not expected:
            expected = payload.get("expected_goals") if isinstance(payload.get("expected_goals"), dict) else {}
        eh, ea = _number(expected.get("home")), _number(expected.get("away"))
        et = _number(expected.get("total"))
        if et is None and eh is not None and ea is not None:
            et = eh + ea
        valid.append({"row": row, "p": probs, "actual": actual, "predicted": predicted,
                      "confidence": probs[predicted], "correct": predicted == actual,
                      "hs": hs, "aws": aws, "eh": eh, "ea": ea, "et": et})
    valid.sort(key=lambda x: str(x["row"].get("kickoff_at") or ""), reverse=True)
    favorites = [x for x in valid if x["confidence"] >= 0.50]
    goal_rows = [x for x in valid if x["et"] is not None]
    league = {
        "sample_size": len(valid), "favorite_sample": len(favorites),
        "mean_favorite_confidence": round(sum(x["confidence"] for x in favorites) / len(favorites), 4) if favorites else None,
        "favorite_accuracy": round(sum(x["correct"] for x in favorites) / len(favorites), 4) if favorites else None,
        "expected_total_goals_bias": round(sum(x["hs"] + x["aws"] - x["et"] for x in goal_rows) / len(goal_rows), 4) if goal_rows else None,
        "minimum_sample": 10, "eligible": len(valid) >= 10,
    }

    def team_summary(name):
        key = _team_key(name)
        games = []
        for item in valid:
            row = item["row"]
            is_home = _team_key(row.get("home_team")) == key
            is_away = _team_key(row.get("away_team")) == key
            if not is_home and not is_away:
                continue
            side = "HOME" if is_home else "AWAY"
            games.append({
                "prob": item["p"][side], "won": item["actual"] == side,
                "ef": item["eh"] if is_home else item["ea"],
                "ea": item["ea"] if is_home else item["eh"],
                "af": item["hs"] if is_home else item["aws"],
                "aa": item["aws"] if is_home else item["hs"],
            })
        n = len(games)
        result = {"team": name, "sample_size": n, "minimum_sample": 5, "eligible": n >= 5}
        if n >= 5:
            result["mean_win_probability"] = round(sum(x["prob"] for x in games) / n, 4)
            result["observed_win_rate"] = round(sum(x["won"] for x in games) / n, 4)
            for label, exp_key, actual_key in (("goals_for_bias", "ef", "af"), ("goals_against_bias", "ea", "aa")):
                subset = [x for x in games if x[exp_key] is not None]
                result[label] = round(sum(x[actual_key] - x[exp_key] for x in subset) / len(subset), 4) if subset else None
        return result

    return {
        "success": True, "competition": competition, "kickoff_at": kickoff_at,
        "home_team": team_summary(home_team), "away_team": team_summary(away_team),
        "competition_context": league,
        "data_scope": "Solo snapshots oficiales liquidados con kickoff anterior al encuentro; descriptivo, no modifica probabilidades.",
        "read_only": True, "model_changed": False, "snapshots_written": 0, "provider_calls": 0,
    }


@router.get("/match-context")
def football_match_learning_context(
    competition: str = Query(..., min_length=2, max_length=8),
    home_team: str = Query(..., min_length=1, max_length=120),
    away_team: str = Query(..., min_length=1, max_length=120),
    kickoff_at: str = Query(..., min_length=10, max_length=40),
    limit: int = Query(1000, ge=1, le=1000),
):
    """Return descriptive pre-match lessons from the prior 90 days only."""
    try:
        code = competition.strip().upper()
        target = _utc_datetime(kickoff_at)
        if target is None:
            raise HTTPException(status_code=422, detail="kickoff_at debe incluir una zona horaria válida.")
        window_start = target - timedelta(days=90)
        query = get_supabase_client().table("football_prediction_snapshots").select(
            "provider_match_id,competition_code,kickoff_at,home_team,away_team,model_version,"
            "home_probability,draw_probability,away_probability,expected_goals,prediction_payload,"
            "result_status,actual_home_score,actual_away_score,actual_outcome,settled_at"
        ).eq("competition_code", code).eq("model_version", MODEL_VERSION).eq("result_status", "SETTLED")
        query = query.gte("kickoff_at", window_start.isoformat()).lt("kickoff_at", kickoff_at)
        result = query.order("kickoff_at", desc=True).limit(limit).execute()
        rows = result.data or []
        report = build_match_learning_context(rows, code, home_team, away_team, kickoff_at)
        report["records_returned"] = len(rows)
        report["window_days"] = 90
        report["window_start"] = window_start.isoformat()
        return report
    except HTTPException:
        raise
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Could not build football match learning context")
        raise HTTPException(status_code=503, detail="No se pudo construir el contexto histórico prepartido.") from exc


@router.get("")
def football_postmatch_learning(
    competition: str | None = Query(None, min_length=2, max_length=8),
    limit: int = Query(5000, ge=1, le=5000),
):
    """Read-only diagnostics from settled official football snapshots."""
    try:
        query = get_supabase_client().table("football_prediction_snapshots").select(
            "provider_match_id,competition_code,kickoff_at,home_team,away_team,model_version,"
            "home_probability,draw_probability,away_probability,expected_goals,prediction_payload,"
            "result_status,actual_home_score,actual_away_score,actual_outcome,settled_at"
        ).eq("model_version", MODEL_VERSION).eq("result_status", "SETTLED")
        code = competition.strip().upper() if competition else None
        if code:
            query = query.eq("competition_code", code)
        result = query.order("kickoff_at", desc=True).limit(limit).execute()
        rows = result.data or []
        report = build_postmatch_learning_report(rows, code)
        report["records_returned"] = len(rows)
        report["sample_limit"] = limit
        report["sample_may_be_truncated"] = len(rows) == limit
        return report
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Could not build football post-match learning report")
        raise HTTPException(status_code=503, detail="No se pudo construir el diagnóstico postpartido del fútbol.") from exc



@router.get("/baseline-comparison")
def football_baseline_comparison(
    competition: str = Query(..., min_length=2, max_length=8),
):
    """Compare official settled snapshots with two pre-match historical baselines."""
    try:
        from football_archive import COMPETITIONS
        from football_baselines import build_baseline_comparison

        code = competition.strip().upper()
        config = COMPETITIONS.get(code)
        if not config:
            raise HTTPException(status_code=400, detail=f"Competición no admitida. Usa: {', '.join(COMPETITIONS)}.")

        client = get_supabase_client()
        snapshot_rows = []
        snapshot_limit = 5000
        page_size = 1000
        for offset in range(0, snapshot_limit, page_size):
            query = client.table("football_prediction_snapshots").select(
                "provider_match_id,competition_code,kickoff_at,home_team,away_team,model_version,"
                "home_probability,draw_probability,away_probability,prediction_payload,"
                "result_status,actual_home_score,actual_away_score,actual_outcome"
            ).eq("competition_code", code).eq("model_version", MODEL_VERSION).eq("result_status", "SETTLED")
            page = query.order("kickoff_at", desc=False).range(offset, offset + page_size - 1).execute().data or []
            snapshot_rows.extend(page)
            if len(page) < page_size:
                break

        archive_rows = []
        archive_limit = 12000
        for offset in range(0, archive_limit, page_size):
            query = client.table("football_match_archive").select(
                "match_date,home_team,home_team_key,away_team,away_team_key,home_score,away_score"
            ).eq("competition_code", code)
            page = query.order("match_date", desc=False).range(offset, offset + page_size - 1).execute().data or []
            archive_rows.extend(page)
            if len(page) < page_size:
                break

        alias_rows = client.table("football_team_aliases").select(
            "alias_key,canonical_team_key"
        ).eq("competition_code", code).limit(5000).execute().data or []
        team_aliases = {
            str(row["alias_key"]): str(row["canonical_team_key"])
            for row in alias_rows
            if row.get("alias_key") and row.get("canonical_team_key")
        }

        report = build_baseline_comparison(
            snapshot_rows, archive_rows, code, config["timezone"],
            team_aliases=team_aliases,
            snapshot_truncated=len(snapshot_rows) >= snapshot_limit,
            archive_truncated=len(archive_rows) >= archive_limit,
        )
        report["snapshot_rows_returned"] = len(snapshot_rows)
        return report
    except HTTPException:
        raise
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Could not compare official football forecasts with historical baselines")
        raise HTTPException(status_code=503, detail="No se pudo completar la comparación con las líneas base históricas.") from exc
