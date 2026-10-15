"""Read-only API endpoints for validating historical tennis profiles.

These endpoints expose historical indicators only. They intentionally do not
emit winner probabilities until a separate model has been backtested.
"""
import logging

import requests
from fastapi import APIRouter, HTTPException, Query

from tennis_history import HistoricalDataError, get_player_profile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tennis/history", tags=["Tennis history"])


@router.get("/profile")
def player_profile(
    player_name: str = Query(..., min_length=1, max_length=120),
    league: str = Query("ATP", pattern="^(?i:ATP|WTA)$"),
    cutoff_date: str | None = Query(None, description="Fecha límite exclusiva YYYY-MM-DD"),
    surface: str | None = Query(None),
    lookback_days: int = Query(365, ge=30, le=730),
):
    try:
        return get_player_profile(
            player_name=player_name,
            league=league,
            cutoff_date=cutoff_date,
            surface=surface,
            lookback_days=lookback_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HistoricalDataError as exc:
        logger.warning("Historical tennis profile unavailable: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "TENNIS_HISTORY_SOURCE_ERROR",
                "message": str(exc),
            },
        ) from exc
    except requests.RequestException as exc:
        logger.exception("Upstream error for historical tennis profile")
        raise HTTPException(
            status_code=502,
            detail={
                "error": "TENNIS_HISTORY_SOURCE_ERROR",
                "message": "No fue posible consultar los históricos de tenis.",
            },
        ) from exc


@router.get("/status")
def historical_status():
    return {
        "success": True,
        "status": "historical-profile-preview",
        "leagues": ["ATP", "WTA"],
        "model_status": "not_available",
        "available_metrics": [
            "last_5_and_10_matches",
            "recent_win_rate",
            "surface_win_rate",
            "latest_ranking_seen_in_window",
            "rest_days",
            "recent_workload",
            "service_and_return_stats_when_reported",
        ],
        "limitations": [
            "Profiles are based on public annual CSVs and a limited 30-730 day window.",
            "Player matching uses normalized names and can be ambiguous.",
            "Historical source licensing must be reviewed before commercial use.",
            "No probabilities or winner predictions are produced by these endpoints.",
        ],
    }
