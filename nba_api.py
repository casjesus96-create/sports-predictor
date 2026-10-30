import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from nba_client import get_game, get_upcoming_games, _get_boxscore_for_game
from nba_player_stats import fetch_player_boxscore
from nba_analyzer import analyze_nba_game
from nba_prediction import MODEL_VERSION
from nba_quarter_validation import evaluate_quarter_projections, select_latest_pregame_snapshots
from nba_repository import (
    save_nba_analysis, refresh_nba_analysis, get_nba_predictions, settle_nba_prediction,
    get_nba_performance,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/nba", tags=["NBA"])
UTC = timezone.utc


@router.get("/boxscore/{game_id}")
def nba_player_boxscore(game_id: str):
    """Return ESPN boxscore player points, assists, rebounds, blocks, and steals."""
    try:
        report = fetch_player_boxscore(game_id)
        if not report.get("available"):
            return {**report, "message": "ESPN todavía no ofrece estadísticas individuales para este encuentro."}
        return report
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error obteniendo estadísticas individuales NBA game_id=%s", game_id)
        raise HTTPException(status_code=502, detail={"error": "NBA_BOXSCORE_ERROR",
            "message": "No fue posible obtener las estadísticas individuales NBA.", "details": str(exc)}) from exc


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


@router.post("/refresh/{game_id}")
def nba_refresh_analysis(game_id: str):
    """Reconsulta datos pregame y actualiza el detalle de una proyección pendiente."""
    try:
        analysis = analyze_nba_game(game_id)
        if not analysis.get("success"):
            return analysis
        persistence = refresh_nba_analysis(analysis)
        return {"success": True, "sport": "NBA", "league": "NBA", "model_version": MODEL_VERSION,
            "game_id": str(game_id), "prediction": analysis.get("prediction"),
            "projections": analysis.get("projections") or {}, "factors": analysis.get("factors") or {},
            "data_cutoff": analysis.get("data_cutoff"), "persistence": persistence,
            "refreshed": bool(persistence.get("refreshed"))}
    except Exception as exc:
        logger.exception("Error actualizando análisis NBA game_id=%s", game_id)
        raise HTTPException(status_code=500, detail={"error": "NBA_ANALYSIS_REFRESH_ERROR",
            "message": "No fue posible actualizar el análisis estadístico NBA.", "details": str(exc)}) from exc


@router.post("/predict/{game_id}")
def nba_predict(game_id: str):
    try:
        analysis = analyze_nba_game(game_id)
        if not analysis.get("success"):
            return analysis
        persistence = save_nba_analysis(analysis)
        return {"success": True, "sport": "NBA", "league": "NBA", "model_version": MODEL_VERSION, "game_id": str(game_id), "prediction": analysis.get("prediction"), "projections": analysis.get("projections") or {}, "factors": analysis.get("factors") or {}, "data_cutoff": analysis.get("data_cutoff"), "persistence": persistence}
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


@router.post("/settle-pending")
def nba_settle_pending():
    """Revisa y liquida las proyecciones NBA pendientes con las mismas validaciones individuales."""
    rows = get_nba_predictions(status="PENDING", limit=500, model_version=MODEL_VERSION)
    settled = 0
    still_pending = 0
    errors = 0
    results = []

    for row in rows:
        event_id = str(row.get("event_id") or "")
        if not event_id:
            errors += 1
            results.append({"event_id": None, "success": False, "message": "La proyección no contiene event_id."})
            continue

        try:
            result = nba_settle(
                event_id,
                prediction_id=str(row.get("id")) if row.get("id") else None,
            )
            settlement = result.get("settlement") or {}
            if result.get("success") and settlement.get("success"):
                settled += 1
                results.append({
                    "event_id": event_id,
                    "success": True,
                    "prediction_result": settlement.get("prediction_result"),
                })
            elif result.get("status") == "PENDING":
                still_pending += 1
                results.append({
                    "event_id": event_id,
                    "success": False,
                    "status": "PENDING",
                    "message": result.get("message"),
                })
            else:
                errors += 1
                results.append({
                    "event_id": event_id,
                    "success": False,
                    "message": result.get("message") or settlement.get("message") or "No se pudo liquidar la proyección.",
                })
        except Exception as exc:
            errors += 1
            logger.exception("Error al liquidar pendiente NBA game_id=%s", event_id)
            results.append({"event_id": event_id, "success": False, "message": str(exc)})

    summary = {
        "checked": len(rows),
        "settled": settled,
        "still_pending": still_pending,
        "errors": errors,
    }
    return {
        "success": True,
        "sport": "NBA",
        "model_version": MODEL_VERSION,
        "summary": summary,
        "message": (
            f"Revisión terminada. Liquidadas: {settled}; "
            f"pendientes: {still_pending}; errores: {errors}."
        ),
        "results": results,
    }


@router.get("/audit/player-impact")
def nba_player_impact_audit(limit: int = Query(500, ge=1, le=500)):
    """Read-only chronological audit of persisted pregame player-impact observations."""
    try:
        rows = get_nba_predictions(limit=limit, model_version=MODEL_VERSION)
        observations = []
        for row in rows:
            features = row.get("features") or {}
            for entry in features.get("player_impact_history") or []:
                if not isinstance(entry, dict):
                    continue
                game = features.get("game") or {}
                observations.append({
                    "event_id": str(row.get("event_id") or ""),
                    "game": game.get("name") or f"{game.get('away', 'Visitante')} @ {game.get('home', 'Local')}",
                    "kickoff": game.get("kickoff"), "captured_at": entry.get("captured_at"),
                    "data_cutoff": entry.get("data_cutoff"), "result_status": row.get("result_status"),
                    "actual_home_score": row.get("actual_home_score"), "actual_away_score": row.get("actual_away_score"),
                    "official_home_probability": entry.get("official_home_probability"),
                    "official_away_probability": entry.get("official_away_probability"),
                    "impact": entry.get("impact"), "coverage": entry.get("coverage"),
                })
        observations.sort(key=lambda item: (item.get("kickoff") or "", item.get("captured_at") or ""))
        settled = [item for item in observations if item.get("result_status") == "SETTLED" and item.get("actual_home_score") is not None and item.get("actual_away_score") is not None]
        return {"success": True, "sport": "NBA", "model_version": MODEL_VERSION,
            "mode": "read_only_chronological_shadow_audit", "official_probability_changed": False,
            "summary": {"prediction_rows_scanned": len(rows), "historical_snapshots": len(observations),
                "settled_predictions_with_snapshots": len({item['event_id'] for item in settled}),
                "settled_snapshots": len(settled),
                "pending_snapshots": sum(item.get("result_status") == "PENDING" for item in observations)},
            "limitations": [
                "Solo se incluyen snapshots capturados y guardados; no se reconstruyen señales pasadas con datos actuales.",
                "La auditoría no modifica probabilidades ni demuestra mejora predictiva por sí sola.",
                "Los refrescos generan varias observaciones por partido; para métricas por partido debe seleccionarse la última captura anterior al inicio.",
            ], "observations": observations}
    except Exception as exc:
        logger.exception("Error auditando snapshots de impacto individual NBA")
        raise HTTPException(status_code=500, detail="No fue posible auditar los snapshots de impacto individual NBA.") from exc


@router.get("/audit/settlements")
def nba_settlement_integrity_audit(limit: int = Query(50, ge=1, le=100)):
    """Read-only comparison of stored settled NBA rows against current ESPN final status."""
    try:
        rows = get_nba_predictions(status="SETTLED", limit=limit, model_version=MODEL_VERSION)
        checked_at = datetime.now(UTC).isoformat()
        discrepancies = []
        unavailable = []
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def inspect(row):
            event_id = str(row.get("event_id") or "")
            if not event_id:
                return ("unavailable", {"prediction_id": row.get("id"), "reason": "missing_event_id"})
            game = get_game(event_id)
            if not game:
                return ("unavailable", {"event_id": event_id, "prediction_id": row.get("id"),
                    "reason": "ESPN did not return this event"})
            if not game.get("completed") or game.get("home_score") is None or game.get("away_score") is None:
                return ("discrepancy", {"event_id": event_id, "prediction_id": row.get("id"),
                    "stored_status": row.get("result_status"), "provider_status": game.get("status"),
                    "provider_completed": game.get("completed"), "reason": "Stored SETTLED row is not currently confirmed final by ESPN"})
            try:
                stored_home = float(row.get("actual_home_score"))
                stored_away = float(row.get("actual_away_score"))
                provider_home = float(game.get("home_score"))
                provider_away = float(game.get("away_score"))
            except (TypeError, ValueError):
                return ("discrepancy", {"event_id": event_id, "prediction_id": row.get("id"),
                    "reason": "Stored or provider score is missing or invalid"})
            if stored_home != provider_home or stored_away != provider_away:
                return ("discrepancy", {"event_id": event_id, "prediction_id": row.get("id"),
                    "stored_score": {"home": stored_home, "away": stored_away},
                    "provider_score": {"home": provider_home, "away": provider_away},
                    "provider_status": game.get("status"), "reason": "Stored score differs from ESPN"})
            return ("consistent", {"event_id": event_id})

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(inspect, row): row for row in rows}
            consistent = 0
            for future in as_completed(futures):
                try:
                    kind, item = future.result()
                    if kind == "discrepancy":
                        discrepancies.append(item)
                    elif kind == "unavailable":
                        unavailable.append(item)
                    else:
                        consistent += 1
                except Exception as exc:
                    row = futures[future]
                    unavailable.append({"event_id": str(row.get("event_id") or ""),
                        "prediction_id": row.get("id"), "reason": "ESPN verification request failed",
                        "error_type": type(exc).__name__, "details": str(exc)[:200]})
        return {"success": True, "sport": "NBA", "model_version": MODEL_VERSION,
            "mode": "read_only_no_database_changes", "checked_at": checked_at,
            "summary": {"settled_rows_scanned": len(rows), "consistent": consistent,
                "discrepancies": len(discrepancies), "provider_unavailable": len(unavailable)},
            "discrepancies": discrepancies, "provider_unavailable": unavailable,
            "limitations": ["La auditoría compara el estado actual de ESPN con el marcador almacenado; no reconstruye el estado histórico al momento de liquidar.",
                "No reabre, corrige ni modifica ninguna predicción. Cada discrepancia requiere revisión manual antes de cualquier reparación."]}
    except Exception as exc:
        logger.exception("Error auditando integridad de liquidaciones NBA")
        raise HTTPException(status_code=500, detail={"error": "NBA_SETTLEMENT_AUDIT_ERROR",
            "message": "No fue posible verificar la integridad de las liquidaciones NBA.",
            "details": str(exc)}) from exc


@router.get("/performance")
def nba_performance():
    try:
        return get_nba_performance()
    except Exception as exc:
        logger.exception("Error calculando rendimiento NBA")
        raise HTTPException(status_code=500, detail="No fue posible calcular el rendimiento NBA.") from exc


@router.get("/audit/quarter-projections")
def nba_quarter_projection_audit(limit: int = Query(100, ge=1, le=250)):
    """Read-only MAE audit: immutable pregame quarter projections vs ESPN actuals."""
    try:
        # Scan both PENDING and SETTLED snapshots so newly saved quarter projections
        # are visible in coverage diagnostics before their games finish.
        rows = get_nba_predictions(limit=500, model_version=MODEL_VERSION)
        settled_rows = [row for row in rows if row.get("result_status") == "SETTLED"]
        pending_rows = [row for row in rows if row.get("result_status") == "PENDING"]
        has_quarter_projection = lambda row: (
            (((row.get("features") or {}).get("projections") or {}).get("quarter_points") or {}).get("available")
            and len((((row.get("features") or {}).get("projections") or {}).get("quarter_points") or {}).get("periods") or []) >= 4
        )
        eligible_all = [row for row in rows if has_quarter_projection(row)]
        eligible_all_settled = [row for row in settled_rows if has_quarter_projection(row)]
        eligible, duplicate_pregame_snapshots = select_latest_pregame_snapshots(eligible_all_settled)

        actuals = {}
        fetch_errors = []
        # Bound concurrency to avoid hammering ESPN when many historical rows exist.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_get_boxscore_for_game, str(row.get("event_id"))): row for row in eligible if row.get("event_id")}
            for future in as_completed(futures):
                row = futures[future]
                event_id = str(row.get("event_id") or "")
                game = ((row.get("features") or {}).get("game") or {})
                try:
                    _, team_stats = future.result()
                    home_id = str(game.get("home_team_id") or "")
                    away_id = str(game.get("away_team_id") or "")
                    home_stats = team_stats.get(home_id) or {}
                    away_stats = team_stats.get(away_id) or {}
                    home_quarters = home_stats.get("_quarter_points") or []
                    away_quarters = away_stats.get("_quarter_points") or []
                    if len(home_quarters) >= 4 and len(away_quarters) >= 4 and all(v is not None for v in home_quarters[:4] + away_quarters[:4]):
                        actuals[event_id] = {home_id: home_quarters[:4], away_id: away_quarters[:4]}
                    else:
                        fetch_errors.append({"event_id": event_id, "reason": "ESPN no publicó los cuatro cuartos completos."})
                except Exception as exc:
                    logger.warning("Error obteniendo cuartos reales NBA game_id=%s: %s", event_id, exc)
                    response = getattr(exc, "response", None)
                    status_code = getattr(response, "status_code", None)
                    fetch_errors.append({
                        "event_id": event_id,
                        "reason": "No se pudo obtener el boxscore real de ESPN.",
                        "error_type": type(exc).__name__,
                        "http_status": status_code,
                        "details": str(exc)[:300],
                    })

        report = evaluate_quarter_projections(eligible, actuals)
        report["summary"] = {
            "snapshots_scanned": len(rows),
            "settled_snapshots_scanned": len(settled_rows),
            "pending_snapshots_scanned": len(pending_rows),
            "snapshots_with_quarter_projection": len(eligible_all),
            "pending_with_quarter_projection": sum(1 for row in pending_rows if has_quarter_projection(row)),
            "settled_with_quarter_projection": len(eligible_all_settled),
            "unique_pregame_games_selected": len(eligible),
            "duplicate_pregame_snapshots_excluded": duplicate_pregame_snapshots,
            "games_with_actual_quarters": len(actuals),
            "actual_data_fetch_issues": len(fetch_errors),
        }
        report["summary"]["evaluation_skipped"] = report.get("skipped") or {}
        report["fetch_issues"] = fetch_errors
        report["limitations"] = [
            "Solo evalúa proyecciones guardadas antes del inicio; no reconstruye proyecciones con información posterior.",
            "Los MAE son errores históricos descriptivos y no cambian el modelo oficial NBA-1.1.0.",
            "La evaluación depende de que ESPN conserve los parciales por cuarto.",
            "Cuando existen varias capturas válidas pregame del mismo partido, se utiliza únicamente la más reciente anterior al inicio; las demás se contabilizan como duplicadas excluidas.",
        ]
        return report
    except Exception as exc:
        logger.exception("Error auditando proyecciones por cuarto NBA")
        raise HTTPException(status_code=500, detail={
            "error": "NBA_QUARTER_AUDIT_ERROR",
            "message": "No fue posible calcular la validación histórica de proyecciones por cuarto.",
            "details": str(exc),
        }) from exc

