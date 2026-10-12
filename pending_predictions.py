
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, HTTPException

from repository import get_pending_predictions, get_supabase_client

router = APIRouter()

MLB_GAME_URL = "https://statsapi.mlb.com/api/v1.1/game"
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
                        "reason": "Falta el ID del partido o de la predicción.",
                    })
                    results.append(item)
                    continue

                url = f"{MLB_GAME_URL}/{event_id}/feed/live"
                api_response = requests.get(
                    url,
                    headers=MLB_HEADERS,
                    timeout=20,
                )

                if api_response.status_code == 404:
                    item.update({
                        "status": "SKIPPED",
                        "reason": "MLB no encontró el feed de este partido.",
                    })
                    results.append(item)
                    continue

                api_response.raise_for_status()
                feed = api_response.json()

                game_data = feed.get("gameData") or {}
                live_data = feed.get("liveData") or {}
                status_data = game_data.get("status") or {}
                status = status_data.get("abstractGameState")

                if status != "Final":
                    item.update({
                        "status": "NOT_FINAL",
                        "game_status": status,
                        "reason": "MLB todavía no confirma el partido como finalizado.",
                    })
                    results.append(item)
                    continue

                teams = game_data.get("teams") or {}
                home_team = (teams.get("home") or {}).get("name")
                away_team = (teams.get("away") or {}).get("name")

                linescore = live_data.get("linescore") or {}
                score_teams = linescore.get("teams") or {}
                home_score = (score_teams.get("home") or {}).get("runs")
                away_score = (score_teams.get("away") or {}).get("runs")

                if (
                    not home_team
                    or not away_team
                    or home_score is None
                    or away_score is None
                    or home_score == away_score
                ):
                    item.update({
                        "status": "SKIPPED",
                        "reason": "El feed final no contiene un marcador válido.",
                    })
                    results.append(item)
                    continue

                actual_winner = (
                    home_team if int(home_score) > int(away_score)
                    else away_team
                )

                features = record.get("features") or {}
                predicted_winner = features.get("predicted_winner")

                if predicted_winner:
                    normalized = str(predicted_winner).strip().casefold()
                    if normalized == home_team.casefold():
                        predicted_winner = home_team
                    elif normalized == away_team.casefold():
                        predicted_winner = away_team
                    else:
                        predicted_winner = None

                # Si falta el ganador guardado, utilizar únicamente
                # las probabilidades originales de la predicción.
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
                            "reason": "No se puede reconstruir el pronóstico original con seguridad.",
                        })
                        results.append(item)
                        continue

                    predicted_winner = (
                        home_team if home_probability > away_probability
                        else away_team
                    )

                prediction_result = (
                    "CORRECT"
                    if predicted_winner.casefold() == actual_winner.casefold()
                    else "INCORRECT"
                )

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
                    "actual_home_score": int(home_score),
                    "actual_away_score": int(away_score),
                    "settled_at": datetime.now(timezone.utc).isoformat(),
                    "features": updated_features,
                }

                saved = (
                    supabase.table("prediction_snapshots")
                    .update(update_data)
                    .eq("id", prediction_id)
                    .eq("result_status", "PENDING")
                    .execute()
                )

                if not saved.data:
                    item.update({
                        "status": "SKIPPED",
                        "reason": "La predicción ya cambió de estado.",
                    })
                    results.append(item)
                    continue

                item.update({
                    "status": "SETTLED",
                    "home": home_team,
                    "away": away_team,
                    "home_score": int(home_score),
                    "away_score": int(away_score),
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

        return {
            "success": True,
            "checked": len(records),
            "settled": sum(r["status"] == "SETTLED" for r in results),
            "not_final": sum(r["status"] == "NOT_FINAL" for r in results),
            "skipped": sum(r["status"] == "SKIPPED" for r in results),
            "errors": sum(r["status"] == "ERROR" for r in results),
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
