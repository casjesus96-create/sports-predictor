
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, HTTPException

from repository import get_pending_predictions, get_supabase_client, settle_prediction

router = APIRouter()

MLB_GAME_URL = "https://statsapi.mlb.com/api/v1.1/game"
MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0",
    "Accept": "application/json",
}
REQUEST_TIMEOUT = 20


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalized_text(value):
    if value is None:
        return ""
    return str(value).strip().casefold()


def is_cancelled_status(detailed_status):
    """
    Reconoce cancelaciones con o sin motivo.
    Ejemplos:
    - Cancelled
    - Cancelled: Rain
    - Canceled: Weather
    - Game Cancelled
    """
    status = normalized_text(detailed_status)

    return (
        status.startswith("cancelled")
        or status.startswith("canceled")
        or status.startswith("game cancelled")
        or status.startswith("game canceled")
    )


def get_game_status(feed):
    game_data = feed.get("gameData") or {}
    status_data = game_data.get("status") or {}

    return {
        "abstract": status_data.get("abstractGameState"),
        "detailed": status_data.get("detailedState"),
        "coded": status_data.get("codedGameState"),
    }


def mark_cancelled(supabase, record, item, detailed_status):
    """
    Marca como CANCELLED solo si MLB confirma explícitamente
    que el encuentro fue cancelado.

    No lo cuenta como acierto ni como fallo.
    """
    prediction_id = record.get("id")
    features = dict(record.get("features") or {})
    now = utc_now()

    features["settlement"] = {
        **(features.get("settlement") or {}),
        "status": "CANCELLED",
        "reason": detailed_status or "Cancelled",
        "checked_at": now,
        "source": "MLB Stats API live feed",
    }

    update_data = {
        "result_status": "CANCELLED",
        "prediction_result": None,
        "actual_winner": None,
        "actual_home_score": None,
        "actual_away_score": None,
        "settled_at": now,
        "features": features,
    }

    response = (
        supabase.table("prediction_snapshots")
        .update(update_data)
        .eq("id", prediction_id)
        .eq("result_status", "PENDING")
        .execute()
    )

    if not response.data:
        item.update({
            "status": "SKIPPED",
            "reason": (
                "La predicción ya cambió de estado "
                "o fue procesada por otra solicitud."
            ),
        })
        return

    item.update({
        "status": "CANCELLED",
        "game_status": detailed_status,
        "reason": (
            "MLB confirmó la cancelación. "
            "La predicción no cuenta como acierto ni como fallo."
        ),
    })


@router.get("/api/v1/predictions/pending")
def pending_predictions():
    try:
        records = get_pending_predictions()

        return {
            "success": True,
            "total": len(records),
            "predictions": records,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "PENDING_PREDICTIONS_ERROR",
                "message": (
                    "No se pudieron obtener las "
                    "predicciones pendientes."
                ),
                "details": str(exc),
            },
        )


@router.post("/api/v1/predictions/settle-pending")
def settle_pending_predictions():
    try:
        supabase = get_supabase_client()

        response = (
            supabase.table("prediction_snapshots")
            .select("*")
            .eq("result_status", "PENDING")
            .order("created_at", desc=False)
            .execute()
        )

        records = response.data or []
        results = []

        for record in records:
            event_id = str(record.get("event_id") or "")
            prediction_id = record.get("id")

            item = {
                "event_id": event_id,
                "prediction_id": prediction_id,
                "model_version": record.get("model_version"),
            }

            try:
                if not event_id or not prediction_id:
                    item.update({
                        "status": "SKIPPED",
                        "reason": (
                            "Falta el ID del partido "
                            "o de la predicción."
                        ),
                    })
                    results.append(item)
                    continue

                url = f"{MLB_GAME_URL}/{event_id}/feed/live"

                api_response = requests.get(
                    url,
                    headers=MLB_HEADERS,
                    timeout=REQUEST_TIMEOUT,
                )

                if api_response.status_code == 404:
                    item.update({
                        "status": "SKIPPED",
                        "reason": (
                            "MLB no encontró el feed. "
                            "La predicción se conserva pendiente."
                        ),
                    })
                    results.append(item)
                    continue

                api_response.raise_for_status()
                feed = api_response.json()

                game_data = feed.get("gameData") or {}
                live_data = feed.get("liveData") or {}
                status_info = get_game_status(feed)

                abstract_status = status_info["abstract"]
                detailed_status = status_info["detailed"] or ""

                item["game_status"] = (
                    detailed_status or abstract_status or "Unknown"
                )

                # 1. Comprobar cancelación ANTES de comprobar Final.
                # MLB puede devolver abstractGameState="Final" para
                # un encuentro cancelado, sin marcador.
                if is_cancelled_status(detailed_status):
                    mark_cancelled(
                        supabase,
                        record,
                        item,
                        detailed_status,
                    )
                    results.append(item)
                    continue

                # 2. Si el estado es desconocido o el encuentro
                # no es Final, mantener la predicción pendiente.
                if abstract_status != "Final":
                    item.update({
                        "status": "NOT_FINAL",
                        "reason": (
                            "MLB no confirma un resultado final válido. "
                            "El encuentro puede estar pendiente, "
                            "suspendido, aplazado o en curso. "
                            "La predicción permanece pendiente."
                        ),
                    })
                    results.append(item)
                    continue

                # 3. Obtener equipos y marcador final.
                teams = game_data.get("teams") or {}
                home_team = (teams.get("home") or {}).get("name")
                away_team = (teams.get("away") or {}).get("name")

                linescore = live_data.get("linescore") or {}
                score_teams = linescore.get("teams") or {}

                home_score = (
                    (score_teams.get("home") or {}).get("runs")
                )
                away_score = (
                    (score_teams.get("away") or {}).get("runs")
                )

                if (
                    not home_team
                    or not away_team
                    or home_score is None
                    or away_score is None
                ):
                    item.update({
                        "status": "SKIPPED",
                        "reason": (
                            "MLB indica estado Final, pero el feed "
                            "no contiene ambos marcadores. "
                            "No se modificó la predicción."
                        ),
                    })
                    results.append(item)
                    continue

                try:
                    home_score = int(home_score)
                    away_score = int(away_score)
                except (TypeError, ValueError):
                    item.update({
                        "status": "SKIPPED",
                        "reason": (
                            "El marcador devuelto por MLB no es válido."
                        ),
                    })
                    results.append(item)
                    continue

                if home_score == away_score:
                    item.update({
                        "status": "SKIPPED",
                        "reason": (
                            "El marcador está empatado. "
                            "Se necesita un resultado definitivo válido."
                        ),
                    })
                    results.append(item)
                    continue

                actual_winner = (
                    home_team if home_score > away_score else away_team
                )

                # 4. Usar la única ruta central de liquidación.
                # repository.settle_prediction valida el snapshot original,
                # no deriva el pronóstico del resultado real y conserva
                # probabilidades, confianza y versión del modelo.
                settlement = settle_prediction(
                    event_id=event_id,
                    actual_winner=actual_winner,
                    actual_home_score=home_score,
                    actual_away_score=away_score,
                    prediction_id=prediction_id,
                    model_version=record.get("model_version"),
                )

                if not settlement.get("updated"):
                    item.update({
                        "status": "SKIPPED",
                        "reason": settlement.get(
                            "reason",
                            "La predicción permanece pendiente para revisión.",
                        ),
                    })
                    results.append(item)
                    continue

                item.update({
                    "status": "SETTLED",
                    "home": home_team,
                    "away": away_team,
                    "home_score": home_score,
                    "away_score": away_score,
                    "predicted_winner": settlement.get("predicted_winner"),
                    "actual_winner": actual_winner,
                    "prediction_result": settlement.get("prediction_result"),
                })
                results.append(item)

            except requests.RequestException as exc:
                item.update({
                    "status": "ERROR",
                    "reason": f"Error consultando MLB: {str(exc)}",
                })
                results.append(item)

            except Exception as exc:
                item.update({
                    "status": "ERROR",
                    "reason": str(exc),
                })
                results.append(item)

        return {
            "success": True,
            "checked": len(records),
            "settled": sum(
                result["status"] == "SETTLED"
                for result in results
            ),
            "cancelled": sum(
                result["status"] == "CANCELLED"
                for result in results
            ),
            "not_final": sum(
                result["status"] == "NOT_FINAL"
                for result in results
            ),
            "skipped": sum(
                result["status"] == "SKIPPED"
                for result in results
            ),
            "errors": sum(
                result["status"] == "ERROR"
                for result in results
            ),
            "results": results,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "BATCH_SETTLEMENT_ERROR",
                "message": (
                    "No se pudieron procesar las "
                    "predicciones pendientes."
                ),
                "details": str(exc),
            },
        )
