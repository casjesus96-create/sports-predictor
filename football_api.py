"""Football data endpoints backed by football-data.org v4."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from football_data_client import (
    LEAGUES,
    FootballDataError,
    get_competitions,
    get_matches,
    get_standings,
)
from football_model import MODEL_VERSION, predict_1x2

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/football", tags=["Football"])
MODEL_STATUS = "data_integration_only"
UTC = timezone.utc


def _provider_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except FootballDataError as exc:
        if exc.status_code == 400:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        if exc.status_code == 503:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        logger.warning("football-data.org request failed: %s", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected football data integration failure")
        raise HTTPException(
            status_code=502,
            detail="No fue posible consultar los datos de fútbol.",
        ) from exc


def _has_numeric_full_time(match: dict) -> bool:
    full_time = (match.get("score") or {}).get("fullTime") or {}
    return (
        isinstance(full_time.get("home"), int)
        and isinstance(full_time.get("away"), int)
    )


def _reconcile_match(selected_match: dict, history_by_id: dict) -> dict:
    """Prefer completed/current history data over a stale date-filter response."""
    item = dict(selected_match)
    historical = history_by_id.get(item.get("id"))
    if not historical:
        return item

    selected_status = str(item.get("status", "")).upper()
    historical_status = str(historical.get("status", "")).upper()
    historical_has_result = (
        historical_status in {"FINISHED", "AWARDED"}
        and _has_numeric_full_time(historical)
    )

    # A date-filtered fixture can lag behind the competition endpoint. When
    # history has a verified final score, use its status and score together.
    if historical_has_result:
        item["status"] = historical_status
        item["score"] = historical.get("score")
        for key in ("lastUpdated", "utcDate", "matchday", "stage"):
            if historical.get(key) is not None:
                item[key] = historical[key]
    elif selected_status not in {"FINISHED", "AWARDED"} and historical_status in {
        "IN_PLAY", "PAUSED", "EXTRA_TIME", "PENALTY_SHOOTOUT",
        "POSTPONED", "SUSPENDED", "CANCELLED",
    }:
        item["status"] = historical_status
        if historical.get("score") is not None:
            item["score"] = historical["score"]
    return item


@router.get("/health")
def football_health():
    """Reports integration configuration without exposing credentials."""
    import os

    return {
        "success": True,
        "provider": "football-data.org",
        "configured": bool(os.getenv("FOOTBALL_DATA_API_KEY", "").strip()),
        "model_status": MODEL_STATUS,
        "model_activated": False,
        "supported_competitions": list(LEAGUES.keys()),
    }


@router.get("/competitions")
def football_competitions():
    competitions = _provider_call(get_competitions)
    return {
        "success": True,
        "provider": "football-data.org",
        "generated_at": datetime.now(UTC).isoformat(),
        "competitions": competitions,
        "available_count": sum(1 for item in competitions if item["available_in_plan"]),
    }


@router.get("/games")
def football_games(
    competition: str = Query(..., description="Código de liga, por ejemplo PL o PD"),
    date_from: date | None = Query(None, alias="dateFrom"),
    date_to: date | None = Query(None, alias="dateTo"),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="dateFrom no puede ser posterior a dateTo.")
    if date_from and (date_from.year < 1990 or date_from.year > datetime.now(UTC).year + 2):
        raise HTTPException(status_code=400, detail="dateFrom fuera del rango admitido.")
    if date_to and (date_to.year < 1990 or date_to.year > datetime.now(UTC).year + 2):
        raise HTTPException(status_code=400, detail="dateTo fuera del rango admitido.")

    data = _provider_call(
        get_matches,
        competition,
        date_from.isoformat() if date_from else None,
        date_to.isoformat() if date_to else None,
    )
    matches = data.get("matches", [])

    # Query competition history separately: selected-date results are fixtures,
    # not a sufficient training sample and can lag behind final score updates.
    history = _provider_call(get_matches, competition)
    history_matches = history.get("matches", [])
    history_by_id = {
        match.get("id"): match for match in history_matches if match.get("id") is not None
    }
    reconciled_matches = [
        _reconcile_match(match, history_by_id) for match in matches
    ]
    completed = [
        match for match in history_matches
        if str(match.get("status", "")).upper() == "FINISHED"
        and _has_numeric_full_time(match)
    ]

    enriched_matches = []
    for match in reconciled_matches:
        item = dict(match)
        status = str(item.get("status", "")).upper()
        home = (item.get("homeTeam") or {}).get("name")
        away = (item.get("awayTeam") or {}).get("name")
        if status in {"SCHEDULED", "TIMED"} and home and away:
            try:
                item["prediction"] = predict_1x2(home, away, completed)
            except (TypeError, ValueError):
                item["prediction"] = {
                    "available": False,
                    "reason": "No se pudo calcular una estimación válida con los datos disponibles.",
                }
        else:
            item["prediction"] = {
                "available": False,
                "reason": "Las probabilidades prepartido solo se muestran para encuentros no iniciados.",
            }
        enriched_matches.append(item)

    return {
        "success": True,
        "provider": "football-data.org",
        "competition": competition.upper(),
        "generated_at": datetime.now(UTC).isoformat(),
        "count": data.get("resultSet", {}).get("count", len(matches)),
        "filters": {
            "dateFrom": date_from.isoformat() if date_from else None,
            "dateTo": date_to.isoformat() if date_to else None,
        },
        "prediction_model": MODEL_VERSION,
        "training_sample": {
            "completed_matches": len(completed),
            "source": "historial de la competición devuelto por el proveedor",
        },
        "matches": enriched_matches,
    }


@router.get("/standings")
def football_standings(
    competition: str = Query(..., description="Código de liga, por ejemplo PL o PD"),
):
    data = _provider_call(get_standings, competition)
    return {
        "success": True,
        "provider": "football-data.org",
        "competition": competition.upper(),
        "generated_at": datetime.now(UTC).isoformat(),
        "standings": data.get("standings", []),
        "season": data.get("season"),
    }
