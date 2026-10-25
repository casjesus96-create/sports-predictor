
import logging
import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from nfl_client import get_game, get_upcoming_games
from nfl_analyzer import analyze_nfl_game
from nfl_data_coverage import audit_nfl_data_coverage
from nfl_advanced_data import inspect_nfl_advanced_sources
from nfl_pregame_feature_audit import audit_nfl_pregame_feature_coverage
from nfl_repository import (
    save_nfl_analysis,
    settle_nfl_prediction,
    get_nfl_pending_predictions,
    get_nfl_predictions,
    get_nfl_performance,
    get_nfl_calibration,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/nfl", tags=["NFL"])

MODEL_VERSION = "NFL-1.0.0"
UTC = timezone.utc
MINIMUM_FINAL_DELAY = timedelta(hours=4)


def _valid_score(value):
    if value is None or value == "":
        return False

    try:
        number = float(value)
        return math.isfinite(number) and number >= 0
    except (TypeError, ValueError):
        return False


def _final_candidate(game):
    """Comprueba que existan marcadores y haya pasado el plazo mínimo."""
    home_score = game.get("home_score")
    away_score = game.get("away_score")

    if not _valid_score(home_score) or not _valid_score(away_score):
        return False, "El partido todavía no tiene ambos marcadores."

    kickoff_value = game.get("kickoff")
    if not kickoff_value:
        return False, "No hay hora de inicio válida para comprobar el partido."

    try:
        kickoff = datetime.fromisoformat(
            str(kickoff_value).replace("Z", "+00:00")
        )
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=UTC)
        kickoff = kickoff.astimezone(UTC)
    except (TypeError, ValueError):
        return False, "No se pudo interpretar la hora de inicio."

    if datetime.now(UTC) < kickoff + MINIMUM_FINAL_DELAY:
        return False, (
            "Aún no han transcurrido cuatro horas desde el inicio "
            "programado. La proyección permanece pendiente."
        )

    return True, "Marcador disponible y plazo mínimo transcurrido."


def _actual_winner(game):
    home_score = float(game["home_score"])
    away_score = float(game["away_score"])

    if home_score == away_score:
        return None

    return game["home"] if home_score > away_score else game["away"]


def _scores(game):
    return int(float(game["home_score"])), int(float(game["away_score"]))


@router.get("/games")
def nfl_games(limit: int = 20):
    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="limit debe ser mayor que 0.",
        )

    try:
        games = get_upcoming_games(season=2026, limit=min(limit, 50))
        return {
            "success": True,
            "sport": "NFL",
            "season": 2026,
            "generated_at": datetime.now(UTC).isoformat(),
            "total": len(games),
            "games": games,
        }
    except Exception as exc:
        logger.exception("Error obteniendo calendario NFL")
        raise HTTPException(
            status_code=502,
            detail={
                "error": "NFL_GAMES_ERROR",
                "message": "No fue posible obtener los partidos NFL.",
                "details": str(exc),
            },
        ) from exc


@router.get("/games/{game_id}")
def nfl_game(game_id: str):
    try:
        game = get_game(game_id=game_id, season=2026)

        if not game:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NFL_GAME_NOT_FOUND",
                    "message": "No se encontró el partido NFL solicitado.",
                    "game_id": str(game_id),
                },
            )

        return {
            "success": True,
            "sport": "NFL",
            "model_version": MODEL_VERSION,
            "game": game,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error obteniendo partido NFL game_id=%s", game_id)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_GAME_ERROR",
                "message": "Error obteniendo el partido NFL.",
                "details": str(exc),
            },
        ) from exc


@router.get("/analyze/{game_id}")
def analyze_nfl(game_id: str):
    try:
        return analyze_nfl_game(game_id=game_id)
    except Exception as exc:
        logger.exception("Error analizando partido NFL game_id=%s", game_id)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_ANALYSIS_ERROR",
                "message": "Error ejecutando el análisis NFL.",
                "details": str(exc),
            },
        ) from exc


@router.post("/predict/{game_id}")
def predict_nfl(game_id: str):
    """Genera una proyección pregame y guarda su snapshot original."""
    try:
        analysis = analyze_nfl_game(game_id=game_id)

        if not analysis.get("success"):
            return analysis

        persistence = save_nfl_analysis(analysis)

        return {
            "success": True,
            "sport": "NFL",
            "model_version": analysis.get("model_version", MODEL_VERSION),
            "game_id": str(game_id),
            "prediction": analysis.get("prediction"),
            "data_cutoff": analysis.get("data_cutoff"),
            "persistence": persistence,
        }
    except Exception as exc:
        logger.exception("Error guardando proyección NFL game_id=%s", game_id)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_PREDICTION_SAVE_ERROR",
                "message": "No fue posible generar y guardar la proyección NFL.",
                "details": str(exc),
            },
        ) from exc


@router.get("/predictions")
def nfl_predictions(status: str = None, limit: int = 100):
    if status:
        status = status.upper()
        if status not in {"PENDING", "SETTLED"}:
            raise HTTPException(
                status_code=400,
                detail="status debe ser PENDING o SETTLED.",
            )

    try:
        rows = get_nfl_predictions(result_status=status, limit=limit)
        return {
            "success": True,
            "sport": "NFL",
            "model_version": MODEL_VERSION,
            "total": len(rows),
            "predictions": rows,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error obteniendo proyecciones NFL")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_PREDICTIONS_ERROR",
                "message": "No fue posible obtener las proyecciones NFL.",
                "details": str(exc),
            },
        ) from exc


@router.get("/pending")
def nfl_pending():
    try:
        rows = get_nfl_pending_predictions()
        return {
            "success": True,
            "sport": "NFL",
            "model_version": MODEL_VERSION,
            "total": len(rows),
            "predictions": rows,
        }
    except Exception as exc:
        logger.exception("Error obteniendo proyecciones NFL pendientes")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_PENDING_ERROR",
                "message": "No fue posible obtener las proyecciones pendientes.",
                "details": str(exc),
            },
        ) from exc


@router.post("/settle/{game_id}")
def settle_nfl(game_id: str, prediction_id: str = None):
    """Liquida una proyección; los empates se registran como PUSH."""
    try:
        logger.info(
            "Iniciando liquidación NFL: game_id=%s prediction_id=%s model=%s",
            game_id,
            prediction_id,
            MODEL_VERSION,
        )

        game = get_game(game_id=game_id, season=2026)

        if not game:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NFL_GAME_NOT_FOUND",
                    "message": "No se encontró el partido NFL solicitado.",
                    "game_id": str(game_id),
                },
            )

        logger.info(
            "Partido NFL recuperado: game_id=%s home=%s away=%s "
            "home_score=%s away_score=%s kickoff=%s",
            game_id,
            game.get("home"),
            game.get("away"),
            game.get("home_score"),
            game.get("away_score"),
            game.get("kickoff"),
        )

        eligible, reason = _final_candidate(game)
        if not eligible:
            logger.warning(
                "Liquidación NFL no elegible: game_id=%s reason=%s",
                game_id,
                reason,
            )
            return {
                "success": False,
                "game_id": str(game_id),
                "status": "PENDING",
                "message": reason,
            }

        actual_winner = _actual_winner(game)
        home_score, away_score = _scores(game)
        is_tie = home_score == away_score

        logger.info(
            "Enviando liquidación al repositorio: game_id=%s "
            "actual_winner=%s score=%s-%s tie=%s prediction_id=%s",
            game_id,
            actual_winner,
            home_score,
            away_score,
            is_tie,
            prediction_id,
        )

        settlement = settle_nfl_prediction(
            event_id=game_id,
            actual_winner=actual_winner,
            actual_home_score=home_score,
            actual_away_score=away_score,
            prediction_id=prediction_id,
        )

        logger.info(
            "Resultado del repositorio NFL: game_id=%s success=%s "
            "result=%s message=%s",
            game_id,
            settlement.get("success"),
            settlement.get("prediction_result"),
            settlement.get("message"),
        )

        return {
            "success": settlement.get("success", False),
            "sport": "NFL",
            "model_version": MODEL_VERSION,
            "game_id": str(game_id),
            "home": game.get("home"),
            "away": game.get("away"),
            "home_score": home_score,
            "away_score": away_score,
            "actual_winner": "TIE" if is_tie else actual_winner,
            "status": (
                "PUSH"
                if settlement.get("prediction_result") == "PUSH"
                else settlement.get("status")
            ),
            "settlement": settlement,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "NFL_SETTLEMENT_ERROR game_id=%s prediction_id=%s",
            game_id,
            prediction_id,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_SETTLEMENT_ERROR",
                "message": "No fue posible liquidar la proyección NFL.",
                "details": str(exc),
            },
        ) from exc


@router.post("/settle-pending")
def settle_pending_nfl():
    """Revisa proyecciones pendientes sin volver a calcularlas."""
    try:
        pending = get_nfl_pending_predictions()
        settled = []
        still_pending = []
        failed = []

        for prediction in pending:
            event_id = str(prediction.get("event_id") or "")
            if not event_id:
                failed.append({
                    "event_id": event_id,
                    "message": "La proyección no tiene event_id.",
                })
                continue

            try:
                game = get_game(game_id=event_id, season=2026)

                if not game:
                    still_pending.append({
                        "event_id": event_id,
                        "reason": "Partido no encontrado en el calendario.",
                    })
                    continue

                eligible, reason = _final_candidate(game)
                if not eligible:
                    still_pending.append({
                        "event_id": event_id,
                        "reason": reason,
                    })
                    continue

                actual_winner = _actual_winner(game)
                home_score, away_score = _scores(game)

                result = settle_nfl_prediction(
                    event_id=event_id,
                    actual_winner=actual_winner,
                    actual_home_score=home_score,
                    actual_away_score=away_score,
                    prediction_id=prediction.get("id"),
                )

                if result.get("success"):
                    settled.append(result)
                else:
                    failed.append({
                        "event_id": event_id,
                        "message": result.get(
                            "message",
                            "No se pudo liquidar la proyección.",
                        ),
                    })
            except Exception as exc:
                logger.exception(
                    "Error liquidando proyección pendiente NFL event_id=%s",
                    event_id,
                )
                failed.append({
                    "event_id": event_id,
                    "message": str(exc),
                })

        return {
            "success": True,
            "sport": "NFL",
            "model_version": MODEL_VERSION,
            "summary": {
                "checked": len(pending),
                "settled": len(settled),
                "still_pending": len(still_pending),
                "failed": len(failed),
                "push": sum(
                    1 for item in settled
                    if item.get("prediction_result") == "PUSH"
                ),
            },
            "settled": settled,
            "still_pending": still_pending,
            "failed": failed,
        }
    except Exception as exc:
        logger.exception("Error revisando proyecciones pendientes NFL")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_SETTLE_PENDING_ERROR",
                "message": "No fue posible revisar las proyecciones pendientes.",
                "details": str(exc),
            },
        ) from exc


@router.get("/performance")
def nfl_performance():
    try:
        return get_nfl_performance()
    except Exception as exc:
        logger.exception("Error calculando rendimiento NFL")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_PERFORMANCE_ERROR",
                "message": "No fue posible calcular el rendimiento NFL.",
                "details": str(exc),
            },
        ) from exc


@router.get("/calibration")
def nfl_calibration(minimum_sample: int = 30):
    if minimum_sample < 1:
        raise HTTPException(
            status_code=400,
            detail="minimum_sample debe ser mayor que 0.",
        )

    try:
        return get_nfl_calibration(minimum_sample=minimum_sample)
    except Exception as exc:
        logger.exception("Error calculando calibración NFL")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_CALIBRATION_ERROR",
                "message": "No fue posible calcular la calibración NFL.",
                "details": str(exc),
            },
        ) from exc



@router.get("/data-coverage")
def nfl_data_coverage(season: int = 2026, probe_sources: bool = True):
    """Auditoría de cobertura de datos; no modifica las predicciones."""
    if season < 1999 or season > 2100:
        raise HTTPException(
            status_code=400,
            detail="season debe estar entre 1999 y 2100.",
        )

    try:
        return audit_nfl_data_coverage(
            season=season,
            include_source_probes=probe_sources,
        )
    except Exception as exc:
        logger.exception("Error auditando cobertura de datos NFL season=%s", season)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "NFL_DATA_COVERAGE_ERROR",
                "message": "No fue posible auditar la cobertura de datos NFL.",
                "details": str(exc),
            },
        ) from exc


@router.get("/advanced-data-audit")
def nfl_advanced_data_audit(season: int = 2026):
    """Inspecciona esquemas de datasets NFL sin modificar el modelo."""
    if season < 1999 or season > 2100:
        raise HTTPException(
            status_code=400,
            detail="season debe estar entre 1999 y 2100.",
        )

    try:
        return inspect_nfl_advanced_sources(season=season)
    except Exception as exc:
        logger.exception("Error inspeccionando fuentes NFL season=%s", season)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "NFL_ADVANCED_DATA_AUDIT_ERROR",
                "message": "No fue posible inspeccionar las fuentes avanzadas NFL.",
                "details": str(exc),
            },
        ) from exc


@router.get("/pregame-feature-coverage")
def nfl_pregame_feature_coverage(season: int = 2026):
    """Audita cobertura de variables NFL con corte estricto pre-kickoff."""
    if season < 1999 or season > 2100:
        raise HTTPException(
            status_code=400,
            detail="season debe estar entre 1999 y 2100.",
        )

    try:
        return audit_nfl_pregame_feature_coverage(season=season)
    except Exception as exc:
        logger.exception("Error auditando cobertura pregame NFL season=%s", season)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "NFL_PREGAME_FEATURE_AUDIT_ERROR",
                "message": "No fue posible auditar la cobertura pregame NFL.",
                "details": str(exc),
            },
        ) from exc


@router.get("/status")
def nfl_status():
    return {
        "success": True,
        "sport": "NFL",
        "season": 2026,
        "model_version": MODEL_VERSION,
        "status": "active",
        "prediction_persistence": "active",
        "settlement": "active",
        "calibration": "active",
        "generated_at": datetime.now(UTC).isoformat(),
    }
