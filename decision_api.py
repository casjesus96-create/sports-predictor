"""API for the Sports Predictor Centro de Decisión.

Uses immutable official prediction snapshots when selected and stores every
completed evaluation for later outcome review. The engine never predicts by
itself and no result is guaranteed.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from decision_engine import evaluate_decision
from repository import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/decision", tags=["Centro de Decisión"])


class DecisionEvaluationRequest(BaseModel):
    # Manual mode fields. When prediction_snapshot_id is supplied, the saved
    # snapshot is the source of truth and client-supplied probabilities are ignored.
    sport: Literal["MLB", "NFL", "NBA", "TENNIS"] | None = None
    model_probability: float | None = Field(default=None, gt=0, lt=1)
    decimal_odds: float = Field(gt=1, le=1000)
    data_quality: int | None = Field(default=None, ge=0, le=100)
    risk_signals: list[str] = Field(default_factory=list, max_length=20)
    market_probability: float | None = Field(default=None, gt=0, lt=1)
    opponent_model_probability: float | None = Field(default=None, gt=0, lt=1)
    opponent_decimal_odds: float | None = Field(default=None, gt=1, le=1000)
    prediction_snapshot_id: str | None = None
    selected_side: Literal["home", "away"] | None = None


def _as_float(value):
    try:
        number = float(value)
        return number if 0 < number < 1 else None
    except (TypeError, ValueError):
        return None


def _sport_from_row(row: dict) -> str:
    league = str(row.get("league") or "").strip().upper()
    sport = str(row.get("sport") or "").strip().upper()
    value = league or sport
    aliases = {
        "BASEBALL": "MLB",
        "MLB": "MLB",
        "AMERICAN FOOTBALL": "NFL",
        "FOOTBALL": "NFL",
        "NFL": "NFL",
        "BASKETBALL": "NBA",
        "NBA": "NBA",
        "TENNIS": "TENNIS",
    }
    return aliases.get(value, value)


def _snapshot_summary(row: dict) -> dict | None:
    home_probability = _as_float(row.get("home_probability"))
    away_probability = _as_float(row.get("away_probability"))
    if home_probability is None or away_probability is None:
        return None

    features = row.get("features") or {}
    game = features.get("game") or {}
    home = game.get("home") or game.get("home_team") or "Local"
    away = game.get("away") or game.get("away_team") or "Visitante"
    if isinstance(home, dict):
        home = home.get("name") or home.get("full_name") or home.get("abbreviation") or "Local"
    if isinstance(away, dict):
        away = away.get("name") or away.get("full_name") or away.get("abbreviation") or "Visitante"

    sport = _sport_from_row(row)
    if sport not in {"MLB", "NFL", "NBA", "TENNIS"}:
        return None

    return {
        "id": str(row.get("id")),
        "event_id": str(row.get("event_id") or ""),
        "sport": sport,
        "league": row.get("league"),
        "model_version": row.get("model_version"),
        "created_at": row.get("created_at"),
        "result_status": row.get("result_status"),
        "home": str(home),
        "away": str(away),
        "home_probability": home_probability,
        "away_probability": away_probability,
        "data_quality": row.get("data_quality"),
        "confidence": row.get("confidence"),
    }


@router.get("/predictions")
def list_saved_predictions(limit: int = Query(100, ge=1, le=300)):
    """List recent pending official snapshots usable by the decision center."""
    try:
        response = (
            get_supabase_client()
            .table("prediction_snapshots")
            .select(
                "id,event_id,sport,league,model_version,created_at,result_status,"
                "home_probability,away_probability,data_quality,confidence,features"
            )
            .eq("result_status", "PENDING")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        predictions = [
            summary for row in (response.data or [])
            if (summary := _snapshot_summary(row)) is not None
        ]
        return {"success": True, "total": len(predictions), "predictions": predictions}
    except Exception as exc:
        logger.exception("No se pudieron listar los snapshots para Centro de Decisión")
        raise HTTPException(
            status_code=503,
            detail="No fue posible consultar las predicciones guardadas. Revisa la conexión con Supabase.",
        ) from exc


@router.post("/evaluate")
def evaluate(request: DecisionEvaluationRequest):
    supabase = get_supabase_client()
    snapshot = None
    snapshot_summary = None

    if request.prediction_snapshot_id:
        if not request.selected_side:
            raise HTTPException(status_code=422, detail="Selecciona si quieres evaluar al equipo local o visitante.")
        try:
            response = (
                supabase.table("prediction_snapshots")
                .select(
                    "id,event_id,sport,league,model_version,created_at,result_status,"
                    "home_probability,away_probability,data_quality,confidence,features"
                )
                .eq("id", request.prediction_snapshot_id)
                .limit(1)
                .execute()
            )
            rows = response.data or []
            if not rows:
                raise HTTPException(status_code=404, detail="No se encontró la predicción guardada.")
            snapshot = rows[0]
            if str(snapshot.get("result_status") or "").upper() != "PENDING":
                raise HTTPException(status_code=409, detail="Solo se pueden evaluar predicciones que sigan pendientes.")
            snapshot_summary = _snapshot_summary(snapshot)
            if not snapshot_summary:
                raise HTTPException(status_code=422, detail="La predicción guardada no contiene probabilidades válidas para ambos equipos.")
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Error leyendo snapshot para evaluación")
            raise HTTPException(status_code=503, detail="No fue posible leer la predicción desde Supabase.") from exc

        sport = snapshot_summary["sport"]
        home_probability = snapshot_summary["home_probability"]
        away_probability = snapshot_summary["away_probability"]
        probability = home_probability if request.selected_side == "home" else away_probability
        opponent_probability = away_probability if request.selected_side == "home" else home_probability
        quality_value = snapshot_summary.get("data_quality")
        try:
            quality = max(0, min(100, int(float(quality_value)))) if quality_value is not None else 0
        except (TypeError, ValueError):
            quality = 0
        features = snapshot.get("features") or {}
        game = features.get("game") or {}
        home_team = snapshot_summary["home"]
        away_team = snapshot_summary["away"]
        selected_team = home_team if request.selected_side == "home" else away_team
        opponent_team = away_team if request.selected_side == "home" else home_team
        model_version = snapshot.get("model_version")
        event_id = str(snapshot.get("event_id") or "")
        source_snapshot_id = str(snapshot.get("id"))
    else:
        if request.sport is None or request.model_probability is None:
            raise HTTPException(
                status_code=422,
                detail="En modo manual debes indicar deporte y probabilidad del modelo, o seleccionar una predicción guardada.",
            )
        sport = request.sport
        probability = request.model_probability
        opponent_probability = request.opponent_model_probability
        quality = request.data_quality if request.data_quality is not None else 100
        selected_team = None
        opponent_team = None
        model_version = None
        event_id = None
        source_snapshot_id = None

    try:
        result = evaluate_decision(
            sport=sport,
            model_probability=probability,
            decimal_odds=request.decimal_odds,
            data_quality=quality,
            risk_signals=request.risk_signals,
            market_probability=request.market_probability,
            opponent_model_probability=opponent_probability,
            opponent_decimal_odds=request.opponent_decimal_odds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    payload = {
        "prediction_snapshot_id": source_snapshot_id,
        "event_id": event_id,
        "sport": sport,
        "model_version": model_version,
        "selected_side": request.selected_side if snapshot else "manual",
        "selected_team": selected_team,
        "opponent_team": opponent_team,
        "model_probability": probability,
        "decimal_odds": request.decimal_odds,
        "data_quality": quality,
        "risk_signals": request.risk_signals,
        "classification": result["classification"],
        "expected_value_percent": result["expected_value_percent"],
        "evaluation": result,
    }
    try:
        saved = supabase.table("decision_evaluations").insert(payload).execute()
        saved_rows = saved.data or []
        if not saved_rows:
            raise RuntimeError("Supabase no devolvió el registro guardado.")
        result["evaluation_id"] = str(saved_rows[0].get("id"))
        result["saved"] = True
        result["source"] = {
            "type": "official_snapshot" if snapshot else "manual",
            "prediction_snapshot_id": source_snapshot_id,
            "event_id": event_id,
            "model_version": model_version,
            "selected_side": request.selected_side if snapshot else None,
            "selected_team": selected_team,
            "opponent_team": opponent_team,
        }
        return result
    except Exception as exc:
        logger.exception("No se pudo guardar la evaluación del Centro de Decisión")
        raise HTTPException(
            status_code=503,
            detail=(
                "La evaluación no se guardó. Aplica primero la migración SQL "
                "supabase/migrations/20261018190000_create_decision_evaluations.sql en Supabase."
            ),
        ) from exc


@router.get("/history")
def decision_history(limit: int = Query(100, ge=1, le=500)):
    """Read saved evaluations and derive outcome when the source prediction settles."""
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("decision_evaluations")
            .select("*")
            .order("evaluated_at", desc=True)
            .limit(limit)
            .execute()
        )
        evaluations = response.data or []
        snapshot_ids = list({
            str(row.get("prediction_snapshot_id"))
            for row in evaluations
            if row.get("prediction_snapshot_id")
        })
        snapshots_by_id = {}
        if snapshot_ids:
            snapshots_response = (
                supabase.table("prediction_snapshots")
                .select("id,result_status,actual_winner,actual_home_score,actual_away_score,features")
                .in_("id", snapshot_ids)
                .execute()
            )
            snapshots_by_id = {
                str(row.get("id")): row for row in (snapshots_response.data or [])
            }

        history = []
        settled = correct = incorrect = 0
        for row in evaluations:
            item = dict(row)
            snapshot_id = str(row.get("prediction_snapshot_id") or "")
            source = snapshots_by_id.get(snapshot_id)
            outcome = "MANUAL_UNTRACKED"
            actual_winner = None
            if source:
                source_status = str(source.get("result_status") or "").upper()
                actual_winner = source.get("actual_winner")
                if source_status == "CANCELLED":
                    outcome = "CANCELLED"
                elif source_status == "SETTLED" and actual_winner:
                    selected_team = str(row.get("selected_team") or "").strip().casefold()
                    outcome = "CORRECT" if selected_team and selected_team == str(actual_winner).strip().casefold() else "INCORRECT"
                    settled += 1
                    if outcome == "CORRECT":
                        correct += 1
                    else:
                        incorrect += 1
                else:
                    outcome = "PENDING"
            elif row.get("prediction_snapshot_id"):
                outcome = "SOURCE_SNAPSHOT_UNAVAILABLE"
            item["outcome_status"] = outcome
            item["actual_winner"] = actual_winner
            if source:
                item["actual_home_score"] = source.get("actual_home_score")
                item["actual_away_score"] = source.get("actual_away_score")
            history.append(item)

        return {
            "success": True,
            "total": len(history),
            "settled": settled,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy_percentage": round(correct / settled * 100, 2) if settled else None,
            "evaluations": history,
        }
    except Exception as exc:
        logger.exception("No se pudo consultar historial del Centro de Decisión")
        raise HTTPException(
            status_code=503,
            detail="No fue posible consultar el historial. Comprueba que la tabla decision_evaluations exista.",
        ) from exc
