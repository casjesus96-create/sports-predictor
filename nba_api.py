import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from nba_client import get_game, get_upcoming_games
from nba_analyzer import analyze_nba_game
from nba_prediction import MODEL_VERSION
from nba_repository import (
    save_nba_analysis, get_nba_predictions, settle_nba_prediction,
    get_nba_performance,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/nba", tags=["NBA"])
UTC = timezone.utc


@router.get("/status")
def nba_status():
    return {"success": True, "sport": "NBA", "league": "NBA", "model_version": MODEL_VERSION, "status": "active", "pregame_only": True}


@router.get("/games")
def nba_games(days: int = Query(21, ge=1, le=45), limit: int = Query(30, ge=1, le=100)):
    try:
        games = get_upcoming_games(days=days, limit=limit)
        return {"success": True, "sport": "NBA", "league": "NBA", "model_version": MODEL_VERSION, "generated_at": datetime.now(UTC).isoformat(), "total": len(games), "games": games}
    except Exception as exc:
        logger.exception("Error obteniendo calendario NBA")
        raise HTTPException(status_code=502, detail={"error": "NBA_GAMES_ERROR", "message": "No fue posible obtener el calendario NBA.", "details": str(exc)}) from exc


@router.get("/analyze/{game_id}")
def nba_analyze(game_id: str):
    try:
        return analyze_nba_game(game_id)
    except Exception as exc:
        logger.exception("Error analizando NBA game_id=%s", game_id)
        raise HTTPException(status_code=502, detail={"error": "NBA_ANALYSIS_ERROR", "message": "No fue posible analizar el partido NBA.", "details": str(exc)}) from exc


@router.post("/predict/{game_id}")
def nba_predict(game_id: str):
    try:
        analysis = analyze_nba_game(game_id)
        if not analysis.get("success"):
            return analysis
        persistence = save_nba_analysis(analysis)
        return {"success": True, "sport": "NBA", "league": "NBA", "model_version": MODEL_VERSION, "game_id": str(game_id), "prediction": analysis.get("prediction"), "data_cutoff": analysis.get("data_cutoff"), "persistence": persistence}
    except Exception as exc:
        logger.exception("Error guardando predicción NBA game_id=%s", game_id)
        raise HTTPException(status_code=500, detail={"error": "NBA_PREDICTION_SAVE_ERROR", "message": "No fue posible guardar la proyección NBA.", "details": str(exc)}) from exc


@router.get("/predictions")
def nba_predictions(status: str = None, limit: int = Query(100, ge=1, le=500)):
    if status and status.upper() not in {"PENDING", "SETTLED"}:
        raise HTTPException(status_code=400, detail="status debe ser PENDING o SETTLED.")
    try:
        rows = get_nba_predictions(status=status, limit=limit)
        return {"success": True, "sport": "NBA", "model_version": MODEL_VERSION, "total": len(rows), "predictions": rows}
    except Exception as exc:
        logger.exception("Error listando predicciones NBA")
        raise HTTPException(status_code=500, detail="No fue posible obtener las proyecciones NBA.") from exc


@router.get("/pending")
def nba_pending():
    return {"success": True, "sport": "NBA", "model_version": MODEL_VERSION, "predictions": get_nba_predictions(status="PENDING", limit=500)}


@router.post("/settle/{game_id}")
def nba_settle(game_id: str, prediction_id: str = None):
    try:
        game = get_game(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="No se encontró el partido NBA.")
        if not game.get("completed") or game.get("home_score") is None or game.get("away_score") is None:
            return {"success": False, "status": "PENDING", "game_id": str(game_id), "message": "El partido todavía no figura como final; la proyección permanece pendiente."}
        try:
            kickoff = datetime.fromisoformat(str(game.get("kickoff")).replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=UTC)
            if datetime.now(UTC) < kickoff.astimezone(UTC) + timedelta(hours=3):
                return {"success": False, "status": "PENDING", "game_id": str(game_id), "message": "Aún no transcurrieron tres horas desde el inicio; espera antes de liquidar."}
        except (TypeError, ValueError):
            return {"success": False, "status": "PENDING", "game_id": str(game_id), "message": "No se pudo validar la hora del partido; se conserva pendiente."}
        result = settle_nba_prediction(game_id, game["home_score"], game["away_score"], prediction_id)
        return {"success": result.get("success", False), "sport": "NBA", "model_version": MODEL_VERSION, "game": game, "settlement": result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error liquidando NBA game_id=%s", game_id)
        raise HTTPException(status_code=500, detail={"error": "NBA_SETTLEMENT_ERROR", "message": "No fue posible liquidar la proyección NBA.", "details": str(exc)}) from exc


@router.get("/performance")
def nba_performance():
    try:
        return get_nba_performance()
    except Exception as exc:
        logger.exception("Error calculando rendimiento NBA")
        raise HTTPException(status_code=500, detail="No fue posible calcular el rendimiento NBA.") from exc
