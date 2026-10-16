"""Tennis calendar and candidate Elo projection API.

Live projections remain a validation candidate until chronological backtests,
immutable snapshot persistence, and settlement are verified.
"""
import logging
from datetime import date, datetime, timezone

import requests
from fastapi import APIRouter, HTTPException, Query

from tennis_client import get_matches
from tennis_history import HistoricalDataError, load_year
from tennis_prediction import (
    DEFAULT_K_FACTOR,
    MODEL_VERSION,
    build_pre_match_ratings,
    project_match,
)

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
        "model_status": "candidate_not_activated",
        "candidate_model": MODEL_VERSION,
        "message": (
            "El motor Elo general está disponible para pruebas controladas. "
            "No se considera modelo oficial de producción hasta completar "
            "validación cronológica, registro inmutable y liquidación."
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
            "model_status": "candidate_not_activated",
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


@router.get("/projection")
def tennis_candidate_projection(
    player1: str = Query(..., min_length=2, max_length=120),
    player2: str = Query(..., min_length=2, max_length=120),
    league: str = Query("ATP", pattern="^(?i:ATP|WTA)$"),
    cutoff_date: str = Query(..., description="Fecha del partido/corte exclusiva YYYY-MM-DD"),
    warmup_years: int = Query(3, ge=1, le=10),
    k_factor: float = Query(DEFAULT_K_FACTOR, ge=4.0, le=64.0),
):
    """Generate a candidate general-Elo projection using only pre-cutoff results."""
    try:
        try:
            cutoff = date.fromisoformat(cutoff_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="cutoff_date debe tener formato YYYY-MM-DD.",
            ) from exc

        league_value = league.strip().upper()
        first_year = max(1968, cutoff.year - warmup_years)
        historical_rows = []
        for year in range(first_year, cutoff.year + 1):
            historical_rows.extend(load_year(league_value, year))

        rating_state = build_pre_match_ratings(
            historical_rows,
            cutoff_date=cutoff,
            k_factor=k_factor,
        )
        if rating_state["matches_used"] == 0:
            raise HistoricalDataError(
                "No hay partidos históricos válidos anteriores al corte para construir el rating."
            )
        projection = project_match(player1, player2, rating_state)
        projection.update({
            "league": league_value,
            "model_status": "candidate_not_activated",
            "warmup_years": warmup_years,
            "historical_source": "Jeff Sackmann archive mirror",
            "snapshot_saved": False,
            "notice": (
                "Esta respuesta no se guarda como pronóstico oficial. "
                "No la uses para medir rendimiento de producción hasta integrar "
                "y verificar snapshots inmutables y liquidación."
            ),
        })
        return projection
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HistoricalDataError as exc:
        logger.warning("Historical tennis candidate projection unavailable: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={"error": "TENNIS_HISTORY_SOURCE_ERROR", "message": str(exc)},
        ) from exc
    except requests.RequestException as exc:
        logger.exception("Upstream error for tennis candidate projection")
        raise HTTPException(
            status_code=502,
            detail={
                "error": "TENNIS_HISTORY_SOURCE_ERROR",
                "message": "No fue posible consultar los históricos de tenis.",
            },
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected tennis candidate projection failure")
        raise HTTPException(
            status_code=502,
            detail={
                "error": "TENNIS_PROJECTION_ERROR",
                "message": "No fue posible calcular la proyección candidata.",
            },
        ) from exc
