"""Persistencia y métricas para el único modelo oficial NBA."""
from datetime import datetime, timezone
import math

from repository import get_supabase_client
from nba_prediction import MODEL_VERSION

SPORT = "basketball"
LEAGUE = "NBA"


def save_nba_analysis(analysis):
    if not analysis.get("success"):
        raise ValueError("No se puede guardar un análisis fallido.")
    game = analysis.get("game") or {}
    prediction = analysis.get("prediction") or {}
    event_id = str(game.get("game_id") or "")
    if not event_id:
        raise ValueError("El análisis NBA no contiene game_id.")
    db = get_supabase_client()
    existing = db.table("prediction_snapshots").select("*").eq("event_id", event_id).eq("sport", SPORT).eq("league", LEAGUE).eq("model_version", MODEL_VERSION).eq("result_status", "PENDING").limit(1).execute()
    rows = existing.data or []
    if rows:
        return {"success": True, "saved": True, "existing": True, "prediction_id": rows[0].get("id"), "data": rows[0]}
    payload = {
        "event_id": event_id, "sport": SPORT, "league": LEAGUE,
        "model_version": MODEL_VERSION,
        "created_at": analysis.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "data_cutoff": analysis.get("data_cutoff"),
        "home_probability": prediction.get("home_probability"),
        "away_probability": prediction.get("away_probability"),
        "confidence": prediction.get("confidence"),
        "data_quality": prediction.get("data_quality", 0),
        "features": {"game": game, "factors": analysis.get("factors") or {}, "projections": analysis.get("projections") or {}, "predicted_winner": prediction.get("winner")},
        "result_status": "PENDING", "actual_winner": None,
        "actual_home_score": None, "actual_away_score": None,
        "settled_at": None, "prediction_result": None,
    }
    inserted = db.table("prediction_snapshots").insert(payload).execute()
    saved = inserted.data or []
    return {"success": True, "saved": True, "existing": False, "prediction_id": saved[0].get("id") if saved else None, "data": saved}



def refresh_nba_analysis(analysis):
    """Actualiza el detalle de una proyección pendiente sin duplicarla."""
    if not analysis.get("success"):
        raise ValueError("No se puede actualizar un análisis fallido.")
    game = analysis.get("game") or {}
    event_id = str(game.get("game_id") or "")
    if not event_id:
        raise ValueError("El análisis NBA no contiene game_id.")
    db = get_supabase_client()
    existing = (db.table("prediction_snapshots").select("*")
        .eq("event_id", event_id).eq("sport", SPORT).eq("league", LEAGUE)
        .eq("model_version", MODEL_VERSION).eq("result_status", "PENDING")
        .order("created_at", desc=True).limit(1).execute().data or [])
    if not existing:
        return save_nba_analysis(analysis)
    row = existing[0]
    old_features = row.get("features") or {}
    new_features = {**old_features, "game": game,
        "factors": analysis.get("factors") or {},
        "projections": analysis.get("projections") or {},
        "analysis_refreshed_at": analysis.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "analysis_data_cutoff": analysis.get("data_cutoff")}
    updated = (db.table("prediction_snapshots").update({"features": new_features, "data_cutoff": analysis.get("data_cutoff")})
        .eq("id", row["id"]).eq("result_status", "PENDING").execute())
    saved = updated.data or []
    if not saved:
        raise RuntimeError("No se pudo actualizar la proyección pendiente.")
    return {"success": True, "saved": True, "existing": True, "refreshed": True,
        "prediction_id": row.get("id"), "data": saved[0]}

def get_nba_predictions(status=None, limit=100, model_version=None):
    query = (get_supabase_client().table("prediction_snapshots").select("*")
        .eq("sport", SPORT).eq("league", LEAGUE)
        .order("created_at", desc=True).limit(max(1, min(int(limit), 500))))
    if status:
        query = query.eq("result_status", status.upper())
    if model_version:
        query = query.eq("model_version", model_version)
    return query.execute().data or []


def settle_nba_prediction(event_id, actual_home_score, actual_away_score, prediction_id=None):
    try:
        home_score = float(actual_home_score)
        away_score = float(actual_away_score)
    except (TypeError, ValueError):
        return {"success": False, "updated": False, "message": "Marcadores reales no válidos."}
    if not all(math.isfinite(x) and x >= 0 for x in (home_score, away_score)):
        return {"success": False, "updated": False, "message": "Marcadores reales no válidos."}
    db = get_supabase_client()
    query = (db.table("prediction_snapshots").select("*").eq("event_id", str(event_id))
        .eq("sport", SPORT).eq("league", LEAGUE)
        .eq("model_version", MODEL_VERSION).eq("result_status", "PENDING"))
    if prediction_id:
        query = query.eq("id", prediction_id)
    rows = query.order("created_at", desc=False).limit(1).execute().data or []
    if not rows:
        return {"success": False, "updated": False, "message": "No existe una proyección NBA pendiente para este partido."}
    row = rows[0]
    features = row.get("features") or {}
    game = features.get("game") or {}
    predicted = str(features.get("predicted_winner") or "").strip()
    home_name = str(game.get("home") or "").strip()
    away_name = str(game.get("away") or "").strip()
    actual_winner = home_name if home_score > away_score else away_name if away_score > home_score else "TIE"
    result = "PUSH" if actual_winner == "TIE" else "CORRECT" if predicted.casefold() == actual_winner.casefold() else "INCORRECT"
    updated = db.table("prediction_snapshots").update({
        "result_status": "SETTLED", "prediction_result": result,
        "actual_winner": actual_winner, "actual_home_score": int(home_score),
        "actual_away_score": int(away_score), "settled_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", row["id"]).eq("result_status", "PENDING").execute()
    data = updated.data or []
    if not data:
        return {"success": False, "updated": False, "message": "La proyección ya pudo haber sido liquidada; actualiza la lista."}
    return {"success": True, "updated": True, "event_id": str(event_id), "prediction_id": row.get("id"), "model_version": MODEL_VERSION, "predicted_winner": predicted, "actual_winner": actual_winner, "prediction_result": result, "actual_home_score": int(home_score), "actual_away_score": int(away_score)}


def get_nba_performance():
    rows = get_nba_predictions(limit=500, model_version=MODEL_VERSION)
    settled = [r for r in rows if r.get("result_status") == "SETTLED"]
    correct = sum(r.get("prediction_result") == "CORRECT" for r in settled)
    incorrect = sum(r.get("prediction_result") == "INCORRECT" for r in settled)
    pushes = sum(r.get("prediction_result") == "PUSH" for r in settled)
    decisive = correct + incorrect
    brier = []
    log_loss = []
    for row in settled:
        if row.get("prediction_result") == "PUSH":
            continue
        try:
            p = float(row.get("home_probability"))
            if not math.isfinite(p):
                continue
        except (TypeError, ValueError):
            continue
        features = row.get("features") or {}
        game = features.get("game") or {}
        actual = 1.0 if str(row.get("actual_winner") or "").casefold() == str(game.get("home") or "").casefold() else 0.0
        p = max(0.001, min(0.999, p))
        brier.append((p - actual) ** 2)
        log_loss.append(-(actual * math.log(p) + (1 - actual) * math.log(1 - p)))
    return {
        "success": True, "sport": "NBA", "league": "NBA", "model_version": MODEL_VERSION,
        "summary": {
            "total_predictions": len(rows),
            "pending_predictions": sum(r.get("result_status") == "PENDING" for r in rows),
            "settled_predictions": len(settled),
            "correct_predictions": int(correct), "incorrect_predictions": int(incorrect),
            "push_predictions": int(pushes), "decisive_predictions": decisive,
            "accuracy_percentage": round(correct / decisive * 100, 2) if decisive else 0.0,
            "brier_score": round(sum(brier) / len(brier), 6) if brier else None,
            "log_loss": round(sum(log_loss) / len(log_loss), 6) if log_loss else None,
        },
    }
