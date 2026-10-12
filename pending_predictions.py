
import os
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, HTTPException

from repository import get_pending_predictions, get_supabase_client

router = APIRouter()

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0",
    "Accept": "application/json",
}


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
                "message": "No se pudieron obtener las predicciones pendientes.",
                "details": str(exc),
            },
        )


@router.post("/api/v1/predictions/settle-pending")
def settle_pending_predictions():
    """
    Comprueba todas las predicciones pendientes contra MLB.
    Solo liquida partidos FINALIZADOS y con un pronóstico
    identificable. Actualiza cada registro por su ID exacto.
    """
    try:
        supabase = get_supabase_client()

        response = (
            supabase
            .table("prediction_snapshots")
            .select("*")
            .eq("result_status", "PENDING")
            .order("created_at", desc=False)
            .execute()
        )

        records = response.data or []
        results = []

        for record in records:
            event_id = str(record.get("event_id", ""))
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
                        "reason": "Falta event_id o ID de predicción.",
                    })
                    results.append(item)
                    continue

                api_response = requests.get(
                    MLB_SCHEDULE_URL,
                    params={
                        "sportId": 1,
                        "gamePk": event_id,
                    },
                    headers=MLB_HEADERS,
                    timeout=20,
                )
                api_response.raise_for_status()
                schedule = api_response.json()

                game = None
                for date_block in schedule.get("dates", []):
                    for candidate in date_block.get("games", []):
                        if str(candidate.get("gamePk")) == event_id:
                            game = candidate
                            break
                    if game:
                        break

                if not game:
                    item.update({
                        "status": "SKIPPED",
                        "reason": "MLB no devolvió este partido.",
                    })
                    results.append(item)
                    continue

                game_status = (
                    (game.get("status") or {})
                    .get("abstractGameState")
                )

                if game_status != "Final":
                    item.update({
                        "status": "NOT_FINAL",
                        "game_status": game_status,
                        "reason": "El partido aún no figura como finalizado.",
                    })
                    results.append(item)
                    continue

                teams = game.get("teams") or {}
                home_data = teams.get("home") or {}
                away_data = teams.get("away") or {}

                home_team = (home_data.get("team") or {}).get("name")
                away_team = (away_data.get("team") or {}).get("name")
                home_score = home_data.get("score")
                away_score = away_data.get("score")

                if (
                    not home_team
                    or not away_team
                    or home_score is None
                    or away_score is None
                    or home_score == away_score
                ):
                    item.update({
                        "status": "SKIPPED",
                        "reason": "No hay marcador final válido para determinar el ganador.",
                    })
                    results.append(item)
                    continue

                actual_winner = (
                    home_team if home_score > away_score else away_team
                )

                features = record.get("features") or {}
                stored_winner = features.get("predicted_winner")

                # Solo aceptar el ganador guardado si corresponde
                # a uno de los dos equipos del partido.
                if stored_winner:
                    normalized = str(stored_winner).strip().casefold()
                    if normalized == home_team.casefold():
                        predicted_winner = home_team
                    elif normalized == away_team.casefold():
                        predicted_winner = away_team
                    else:
                        predicted_winner = None
                else:
                    predicted_winner = None

                # Si el ganador no está guardado, reconstruirlo
                # exclusivamente con las probabilidades originales.
                if not predicted_winner:
                    try:
                        home_probability = float(record["home_probability"])
                        away_probability = float(record["away_probability"])
                    except (KeyError, TypeError, ValueError):
                        home_probability = None
                        away_probability = None

                    if (
                        home_probability is None
                        or away_probability is None
                        or home_probability == away_probability
                    ):
                        item.update({
                            "status": "SKIPPED",
                            "reason": "No se puede identificar el pronóstico original de forma segura.",
                        })
                        results.append(item)
                        continue

                    predicted_winner = (
                        home_team
                        if home_probability > away_probability
                        else away_team
                    )

                prediction_result = (
                    "CORRECT"
                    if predicted_winner.casefold() == actual_winner.casefold()
                    else "INCORRECT"
                )

                # Conservar los factores originales y guardar el
                # ganador calculado para futuras auditorías.
                updated_features = dict(features)
                updated_features["predicted_winner"] = predicted_winner
                updated_features["game"] = {
                    **(features.get("game") or {}),
                    "home": home_team,
                    "away": away_team,
                }

                update_data = {
                    "result_status": "SETTLED",
                    "prediction_result": prediction_result,
                    "actual_winner": actual_winner,
                    "actual_home_score": home_score,
                    "actual_away_score": away_score,
                    "settled_at": datetime.now(timezone.utc).isoformat(),
                    "features": updated_features,
                }

                update_response = (
                    supabase
                    .table("prediction_snapshots")
                    .update(update_data)
                    .eq("id", prediction_id)
                    .eq("result_status", "PENDING")
                    .execute()
                )

                if not update_response.data:
                    item.update({
                        "status": "SKIPPED",
                        "reason": "El registro cambió o ya fue liquidado.",
                    })
                    results.append(item)
                    continue

                item.update({
                    "status": "SETTLED",
                    "home": home_team,
                    "away": away_team,
                    "home_score": home_score,
                    "away_score": away_score,
                    "predicted_winner": predicted_winner,
                    "actual_winner": actual_winner,
                    "prediction_result": prediction_result,
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

        settled = sum(1 for row in results if row["status"] == "SETTLED")
        return {
            "success": True,
            "checked": len(records),
            "settled": settled,
            "not_final": sum(1 for row in results if row["status"] == "NOT_FINAL"),
            "skipped": sum(1 for row in results if row["status"] == "SKIPPED"),
            "errors": sum(1 for row in results if row["status"] == "ERROR"),
            "results": results,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "BATCH_SETTLEMENT_ERROR",
                "message": "No se pudieron procesar las predicciones pendientes.",
                "details": str(exc),
            },
        )
