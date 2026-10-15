"""Read-only endpoints for tennis history and research backtesting.

No endpoint here enables a live prediction model. Historical profiles, source
coverage audits, source reconciliation, and the Elo backtest are research tools
pending validation.
"""
import logging

import requests
from fastapi import APIRouter, HTTPException, Query

from tennis_backtest import run_elo_backtest
from tennis_external_source import ExternalTennisSourceError, audit_external_coverage
from tennis_history import HistoricalDataError, get_player_profile
from tennis_reconciliation import audit_external_reconciliation

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
            detail={"error": "TENNIS_HISTORY_SOURCE_ERROR", "message": str(exc)},
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


@router.get("/backtest")
def tennis_historical_backtest(
    league: str = Query("ATP", pattern="^(?i:ATP|WTA)$"),
    start_date: str = Query(..., description="Inicio inclusivo YYYY-MM-DD"),
    end_date: str = Query(..., description="Fin inclusivo YYYY-MM-DD"),
    warmup_years: int = Query(3, ge=1, le=10),
    k_factor: float = Query(32.0, ge=4.0, le=64.0),
):
    """Evaluate a research-only chronological Elo baseline on past results."""
    try:
        return run_elo_backtest(
            league=league,
            start_date=start_date,
            end_date=end_date,
            warmup_years=warmup_years,
            k_factor=k_factor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HistoricalDataError as exc:
        logger.warning("Historical tennis backtest unavailable: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "TENNIS_HISTORY_SOURCE_ERROR",
                "message": str(exc),
            },
        ) from exc
    except requests.RequestException as exc:
        logger.exception("Upstream error for tennis historical backtest")
        raise HTTPException(
            status_code=502,
            detail={
                "error": "TENNIS_HISTORY_SOURCE_ERROR",
                "message": "No fue posible consultar los históricos para el backtest.",
            },
        ) from exc


@router.get("/source-audit")
def tennis_external_source_audit(
    league: str = Query("ATP", pattern="^(?i:ATP|WTA)$"),
    start_date: str = Query(..., description="Inicio inclusivo YYYY-MM-DD"),
    end_date: str = Query(..., description="Fin inclusivo YYYY-MM-DD"),
):
    """Audit independent date-level coverage without merging it into model data."""
    try:
        return audit_external_coverage(
            league=league,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ExternalTennisSourceError as exc:
        logger.warning("External tennis source audit unavailable: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "TENNIS_EXTERNAL_SOURCE_ERROR",
                "message": str(exc),
            },
        ) from exc


@router.get("/reconciliation-audit")
def tennis_external_reconciliation_audit(
    league: str = Query("ATP", pattern="^(?i:ATP|WTA)$"),
    start_date: str = Query(..., description="Inicio inclusivo YYYY-MM-DD"),
    end_date: str = Query(..., description="Fin inclusivo YYYY-MM-DD"),
):
    """Return candidate cross-source links for review; never merge historical rows."""
    try:
        return audit_external_reconciliation(
            league=league,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ExternalTennisSourceError, HistoricalDataError) as exc:
        logger.warning("Tennis source reconciliation unavailable: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "TENNIS_RECONCILIATION_SOURCE_ERROR",
                "message": str(exc),
            },
        ) from exc


@router.get("/status")
def historical_status():
    return {
        "success": True,
        "status": "historical-profile-preview",
        "leagues": ["ATP", "WTA"],
        "model_status": "not_available",
        "research_backtest": "available",
        "external_source_audit": "available",
        "external_source_reconciliation_audit": "available",
        "available_metrics": [
            "last_5_and_10_matches",
            "recent_win_rate",
            "surface_win_rate",
            "latest_ranking_seen_in_window",
            "recent_workload",
            "service_and_return_stats_when_reported",
            "chronological_elo_backtest_accuracy_brier_log_loss",
            "independent_source_monthly_coverage",
            "read_only_source_reconciliation_candidates",
        ],
        "limitations": [
            "Profiles and backtests use public annual CSVs and are limited by source coverage.",
            "Player matching in profiles uses normalized names and can be ambiguous.",
            "Historical source licensing must be reviewed before commercial use.",
            "The Elo backtest is research-only and does not produce live match predictions.",
            "The external source audit does not merge data or reconcile player identities.",
            "Tournament dates are used instead of exact match timestamps in the original Elo archive.",
            "The reconciliation audit only reports candidates and does not prove identity or merge rows.",
            "Valuebetennis CC BY 4.0 attribution is required; the Sackmann archive has separate CC BY-NC-SA 4.0 terms.",
        ],
    }
