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

    # The selected-date response usually contains only that day's fixtures. It
    # is not a valid training sample, so fetch the competition's current-season
    # match history separately and build probabilities from completed matches
    # only. The provider client caches both calls to protect the free-tier quota.
    history = _provider_call(get_matches, competition)
    completed = [
        match for match in history.get("matches", [])
        if str(match.get("status", "")).upper() == "FINISHED"
        and isinstance(((match.get("score") or {}).get("fullTime") or {}).get("home"), int)
        and isinstance(((match.get("score") or {}).get("fullTime") or {}).get("away"), int)
    ]
    enriched_matches = []
    for match in matches:
        item = dict(match)
        status = str(match.get("status", "")).upper()
        home = (match.get("homeTeam") or {}).get("name")
        away = (match.get("awayTeam") or {}).get("name")
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
        "filters": {"dateFrom": date_from.isoformat() if date_from else None,
                    "dateTo": date_to.isoformat() if date_to else None},
        "prediction_model": MODEL_VERSION,
        "training_sample": {"completed_matches": len(completed), "source": "historial de la competición devuelto por el proveedor"},
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
