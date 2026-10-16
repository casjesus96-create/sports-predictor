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
from tennis_prediction_store import (
    get_latest_snapshot,
    get_pending_snapshot,
    performance_summary,
    save_snapshot,
    settle_snapshot,
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


@router.post("/matches/{match_id}/predict")
def save_tennis_match_projection(
    match_id: str,
    league: str = Query("ATP", pattern="^(?i:ATP|WTA)$"),
    match_date: str = Query(..., description="Fecha UTC del partido YYYY-MM-DD"),
    warmup_years: int = Query(3, ge=1, le=10),
    k_factor: float = Query(DEFAULT_K_FACTOR, ge=4.0, le=64.0),
):
    """Create one immutable pre-match snapshot for a verified scheduled match."""
    try:
        try:
            target_date = date.fromisoformat(match_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="match_date debe tener formato YYYY-MM-DD.") from exc

        league_value = league.strip().upper()
        matches = get_matches(league=league_value, days=1, start_date=target_date.isoformat())
        match = next((item for item in matches if str(item.get("match_id")) == str(match_id)), None)
        if not match:
            raise HTTPException(status_code=404, detail="No se encontró ese partido en el calendario oficial de la fuente.")
        if match.get("completed") or str(match.get("status") or "").casefold() in {"in", "post"}:
            raise HTTPException(status_code=409, detail="No se generan pronósticos cuando el partido ya comenzó o terminó.")

        raw_start = match.get("start_time")
        try:
            start_at = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
            if start_at.tzinfo is None:
                start_at = start_at.replace(tzinfo=UTC)
            start_at = start_at.astimezone(UTC)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="La fuente no proporcionó un horario válido para verificar el estado prepartido.") from exc

        now = datetime.now(UTC)
        if start_at <= now:
            raise HTTPException(status_code=409, detail="El horario del partido ya pasó; se rechaza el pronóstico para evitar fuga de información.")

        player1 = match.get("player1") or {}
        player2 = match.get("player2") or {}
        player1_name = str(player1.get("name") or "").strip()
        player2_name = str(player2.get("name") or "").strip()
        if not player1_name or not player2_name:
            raise HTTPException(status_code=502, detail="La fuente no identificó a ambos jugadores.")

        historical_rows = []
        for year in range(max(1968, target_date.year - warmup_years), target_date.year + 1):
            historical_rows.extend(load_year(league_value, year))
        rating_state = build_pre_match_ratings(historical_rows, target_date, k_factor)
        if rating_state["matches_used"] == 0:
            raise HistoricalDataError("No hay partidos históricos válidos anteriores al corte para construir el rating.")
        projection = project_match(player1_name, player2_name, rating_state)
        created_at = datetime.now(UTC)
        if created_at >= start_at:
            raise HTTPException(status_code=409, detail="El partido comenzó durante el cálculo; no se guardó el pronóstico.")

        payload = {
            "event_id": str(match.get("event_id") or match_id),
            "match_id": str(match_id),
            "league": league_value,
            "tournament": match.get("tournament"),
            "round": match.get("round"),
            "player1_id": str(player1.get("id") or "") or None,
            "player1_name": player1_name,
            "player2_id": str(player2.get("id") or "") or None,
            "player2_name": player2_name,
            "model_version": MODEL_VERSION,
            "created_at": created_at.isoformat(),
            "data_cutoff": created_at.isoformat(),
            "player1_probability": projection["player1"]["win_probability"],
            "player2_probability": projection["player2"]["win_probability"],
            "player1_rating": projection["player1"]["rating"],
            "player2_rating": projection["player2"]["rating"],
            "historical_matches_used": projection["historical_matches_used"],
            "features": {
                "match_date": target_date.isoformat(),
                "start_time": start_at.isoformat(),
                "data_source": match.get("data_source"),
                "historical_source": "Jeff Sackmann archive mirror",
                "cutoff_date_exclusive": target_date.isoformat(),
                "warmup_years": warmup_years,
                "k_factor": k_factor,
                "rated_players": projection["rated_players"],
            },
            "result_status": "PENDING",
            "actual_winner_id": None,
            "actual_winner_name": None,
            "settled_at": None,
        }
        saved = save_snapshot(payload)
        return {
            "success": True,
            "model_status": "candidate_not_activated",
            "snapshot_saved": saved["saved"],
            "already_exists": saved["already_exists"],
            "snapshot": saved["snapshot"],
            "notice": "Las probabilidades originales son inmutables. El modelo continúa en fase candidata hasta superar la validación cronológica.",
        }
    except HTTPException:
        raise
    except (ValueError, HistoricalDataError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.exception("Tennis source error while saving prediction")
        raise HTTPException(status_code=502, detail={"error": "TENNIS_DATA_SOURCE_ERROR", "message": "No fue posible verificar el partido o consultar históricos."}) from exc
    except Exception as exc:
        logger.exception("Tennis prediction snapshot failed")
        raise HTTPException(status_code=502, detail={"error": "TENNIS_SNAPSHOT_ERROR", "message": "No fue posible guardar el pronóstico. Verifica que la migración de Supabase esté aplicada."}) from exc


@router.post("/matches/{match_id}/settle")
def settle_tennis_match_projection(
    match_id: str,
    league: str = Query("ATP", pattern="^(?i:ATP|WTA)$"),
):
    """Settle a pending snapshot only when the source confirms the match winner."""
    try:
        league_value = league.strip().upper()
        snapshot = get_pending_snapshot(match_id, league_value)
        if not snapshot:
            existing = get_latest_snapshot(match_id, league_value)
            if existing:
                return {"success": True, "settled": False, "already_settled": True, "snapshot": existing}
            raise HTTPException(status_code=404, detail="No existe un pronóstico guardado para este partido.")

        match_date = ((snapshot.get("features") or {}).get("match_date"))
        if not match_date:
            raise HTTPException(status_code=409, detail="El snapshot no contiene fecha verificable del partido.")
        matches = get_matches(league=league_value, days=1, start_date=match_date)
        match = next((item for item in matches if str(item.get("match_id")) == str(match_id)), None)
        if not match or not match.get("completed") or str(match.get("status") or "").casefold() != "post":
            raise HTTPException(status_code=409, detail="La fuente todavía no confirma el partido como finalizado.")
        p1 = match.get("player1") or {}
        p2 = match.get("player2") or {}
        if p1.get("winner") is True:
            winner = p1
        elif p2.get("winner") is True:
            winner = p2
        else:
            raise HTTPException(status_code=409, detail="El partido figura finalizado, pero no hay ganador oficial inequívoco.")
        settled = settle_snapshot(snapshot, str(winner.get("id") or "") or None, str(winner.get("name") or ""))
        return {"success": True, **settled}
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.exception("Tennis source error while settling prediction")
        raise HTTPException(status_code=502, detail={"error": "TENNIS_RESULT_SOURCE_ERROR", "message": "No fue posible verificar el resultado oficial."}) from exc
    except Exception as exc:
        logger.exception("Tennis settlement failed")
        raise HTTPException(status_code=502, detail={"error": "TENNIS_SETTLEMENT_ERROR", "message": "No fue posible liquidar el pronóstico."}) from exc


@router.get("/performance")
def tennis_prediction_performance(
    league: str | None = Query(None, pattern="^(?i:ATP|WTA)$"),
):
    """Report descriptive metrics from settled, persisted tennis snapshots."""
    try:
        return performance_summary(league)
    except Exception as exc:
        logger.exception("Tennis performance summary unavailable")
        raise HTTPException(status_code=502, detail={"error": "TENNIS_PERFORMANCE_ERROR", "message": "No fue posible calcular el rendimiento de tenis. Verifica la migración y conexión a Supabase."}) from exc
