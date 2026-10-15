"""Read-only API for the initial ATP/WTA tennis section.

No predictions are exposed here: the first milestone validates match data
before a tennis model is introduced.
"""
import logging
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, HTTPException, Query

from tennis_client import get_matches

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tennis", tags=["Tennis"])
UTC = timezone.utc


@router.get("/status")
def tennis_status():
    return {
        "success": True,
        "sport": "Tennis",
        "leagues": ["ATP", "WTA"],
        "status": "data-preview",
        "model_status": "not_available",
        "message": (
            "El calendario y los resultados están disponibles para validación. "
            "El modelo de predicción se habilitará después de validar datos "
            "históricos de jugadores."
        ),
    }


@router.get("/games")
def tennis_games(
    league: str = Query("ATP", pattern="^(?i:ATP|WTA)$"),
    days: int = Query(14, ge=1, le=30),
    start_date: str | None = Query(None, description="Fecha UTC YYYY-MM-DD"),
    limit: int = Query(100, ge=1, le=500),
):
    try:
        if start_date:
            try:
                datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="start_date debe tener formato YYYY-MM-DD.",
                ) from exc
        matches = get_matches(league=league, days=days, start_date=start_date)
        return {
            "success": True,
            "sport": "Tennis",
            "league": league.upper(),
            "start_date": start_date or datetime.now(UTC).date().isoformat(),
            "days": days,
            "generated_at": datetime.now(UTC).isoformat(),
            "total": min(len(matches), limit),
            "matches": matches[:limit],
            "model_status": "not_available",
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.exception("Error consultando scoreboard Tennis league=%s", league)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "TENNIS_DATA_SOURCE_ERROR",
                "message": "No fue posible consultar el calendario de tenis.",
                "details": str(exc),
            },
        ) from exc
    except Exception as exc:
        logger.exception("Error procesando calendario Tennis league=%s", league)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "TENNIS_DATA_ERROR",
                "message": "No fue posible procesar los partidos de tenis.",
                "details": str(exc),
            },
        ) from exc
