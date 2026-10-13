"""Read-only API endpoint for evaluating saved official MLB projections."""
from fastapi import APIRouter, HTTPException, Query
import requests

from mlb_backtest import (
    OFFICIAL_MLB_MODEL,
    actual_tie_after_nine,
    calculate_mlb_backtest_metrics,
    diagnose_projection_storage,
    snapshot_needs_tie_observation,
)
from repository import get_supabase_client

router = APIRouter(prefix="/api/v1/mlb", tags=["MLB backtesting"])
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1/game"
HEADERS = {"User-Agent": "Sports-Predictor/1.0", "Accept": "application/json"}


@router.get("/backtest")
def mlb_backtest(limit: int = Query(default=100, ge=1, le=200)):
    """Evaluate saved snapshots and diagnose projection storage; this endpoint never writes."""
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("prediction_snapshots")
            .select(
                "id,event_id,sport,model_version,result_status,created_at,data_cutoff,"
                "features,actual_home_score,actual_away_score"
            )
            .eq("sport", "baseball")
            .eq("model_version", OFFICIAL_MLB_MODEL)
            .eq("result_status", "SETTLED")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = response.data or []
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "MLB_BACKTEST_DATABASE_ERROR",
                "message": "No se pudieron consultar los snapshots MLB liquidados.",
                "details": str(exc),
            },
        )

    # Diagnose the persisted JSON shape without changing any historical row.
    storage_diagnostics = diagnose_projection_storage(rows)

    # Only call the MLB feed for records with valid saved projections, final scores,
    # and a saved tie probability. Legacy snapshots cannot benefit from this request.
    tie_observations = {}
    feed_errors = []
    candidates = [row for row in rows if snapshot_needs_tie_observation(row)]
    for row in candidates:
        event_id = str(row.get("event_id") or "")
        try:
            response = requests.get(
                f"{MLB_GAME_API}/{event_id}/feed/live",
                timeout=8,
                headers=HEADERS,
            )
            response.raise_for_status()
            observed = actual_tie_after_nine(response.json())
            if isinstance(observed, bool):
                tie_observations[event_id] = observed
        except (requests.RequestException, ValueError) as exc:
            feed_errors.append({"event_id": event_id, "error": str(exc)})

    result = calculate_mlb_backtest_metrics(rows, tie_observations)
    result["queried_snapshots"] = len(rows)
    result["storage_diagnostics"] = storage_diagnostics
    result["tie_feed_candidates"] = len(candidates)
    result["tie_feed_errors"] = len(feed_errors)
    result["tie_feed_error_details"] = feed_errors[:10]
    result["limit"] = limit
    if result["sample_size"] == 0:
        result["message"] = (
            "No hay snapshots liquidados evaluables en esta muestra. "
            "Consulta storage_diagnostics para distinguir snapshots históricos sin "
            "proyecciones de posibles diferencias en la ruta de almacenamiento. "
            "No se reconstruyen ni modifican predicciones históricas."
        )
    return result
