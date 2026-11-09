"""Read-only post-match learning diagnostics for official football snapshots."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

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
        })

    n = len(valid)
    if not n:
        return {
            "success": True, "read_only": True, "model_version": MODEL_VERSION,
            "competition": competition, "sample_size": 0, "excluded_invalid_rows": excluded,
            "metrics": {"accuracy": None, "brier_score": None, "log_loss": None},
            "confidence_bands": [], "surprises": [], "signals": [
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
            "upsets": sum(not item["correct"] for item in subset),
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
    btts_brier = sum((item["btts_p"] - float(item["actual_btts"])) ** 2 for item in btts_rows) / len(btts_rows) if btts_rows else None
    over25_brier = sum((item["over25_p"] - float(item["actual_over25"])) ** 2 for item in over_rows) / len(over_rows) if over_rows else None

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
            "over_2_5_brier_score": round(over25_brier, 5) if over25_brier is not None else None,
            "over_2_5_sample": len(over_rows),
            "upset_count": len(upset_rows),
        },
        "confidence_bands": bands, "surprises": surprises, "signals": signals,
        "data_scope": "Solo snapshots oficiales inmutables FOOTBALL-POISSON-0.5.0 con resultado SETTLED; no usa resultados sin pronóstico prepartido.",
        "learning_policy": "Aprendizaje diagnóstico: mide errores, calibración, sorpresas y residuos de goles. No entrena, recalibra ni modifica probabilidades oficiales.",
        "model_changed": False, "snapshots_written": 0, "provider_calls": 0,
    }


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
