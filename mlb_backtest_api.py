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
SNAPSHOT_FIELDS = (
    "id,event_id,sport,model_version,result_status,created_at,data_cutoff,"
    "features,actual_home_score,actual_away_score"
)


def _read_snapshots(supabase, status, limit):
    response = (
        supabase.table("prediction_snapshots")
        .select(SNAPSHOT_FIELDS)
        .eq("sport", "baseball")
        .eq("model_version", OFFICIAL_MLB_MODEL)
        .eq("result_status", status)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


@router.get("/backtest")
def mlb_backtest(limit: int = Query(default=100, ge=1, le=200)):
    """Evaluate settled snapshots and diagnose recent pending projection storage."""
    try:
        supabase = get_supabase_client()
        settled_rows = _read_snapshots(supabase, "SETTLED", limit)
        # Pending rows show whether the current analysis/persistence path stores projections.
        # This is read-only and intentionally does not rewrite existing snapshots.
        pending_rows = _read_snapshots(supabase, "PENDING", min(limit, 25))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "MLB_BACKTEST_DATABASE_ERROR",
                "message": "No se pudieron consultar los snapshots MLB.",
                "details": str(exc),
            },
        )

    storage_diagnostics = diagnose_projection_storage(settled_rows)
    pending_storage_diagnostics = diagnose_projection_storage(pending_rows)

    tie_observations = {}
    feed_errors = []
    candidates = [row for row in settled_rows if snapshot_needs_tie_observation(row)]
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

    result = calculate_mlb_backtest_metrics(settled_rows, tie_observations)
    result["queried_snapshots"] = len(settled_rows)
    result["storage_diagnostics"] = storage_diagnostics
    result["pending_snapshots_queried"] = len(pending_rows)
    result["pending_storage_diagnostics"] = pending_storage_diagnostics
    result["tie_feed_candidates"] = len(candidates)
    result["tie_feed_errors"] = len(feed_errors)
    result["tie_feed_error_details"] = feed_errors[:10]
    result["limit"] = limit
    if result["sample_size"] == 0:
        result["message"] = (
            "No hay snapshots liquidados evaluables en esta muestra. "
            "Compara storage_diagnostics con pending_storage_diagnostics para "
            "comprobar si los análisis recientes guardan las proyecciones. "
            "No se reconstruyen ni modifican predicciones históricas."
        )
    return result
