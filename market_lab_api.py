"""Read-only cross-sport market laboratory for saved pregame snapshots."""
from __future__ import annotations
import logging
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from market_lab_engine import catalog_for, normalize_sport, project_snapshot
from repository import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/market-lab", tags=["Laboratorio de Mercados"])

def _range(day):
    parsed = date.fromisoformat(day)
    return f"{parsed.isoformat()}T00:00:00+00:00", f"{date.fromordinal(parsed.toordinal()+1).isoformat()}T00:00:00+00:00"

def _central(day):
    start, end = _range(day)
    rows = (get_supabase_client().table("prediction_snapshots").select("*")
        .gte("created_at", start).lt("created_at", end).eq("result_status", "PENDING")
        .order("created_at", desc=True).limit(2000).execute().data or [])
    allowed = {"MLB": "2.0.0-matchup", "NBA": "NBA-1.1.0", "NFL": "NFL-1.0.0"}
    result = []
    for row in rows:
        sport = normalize_sport(row)
        if sport not in allowed or row.get("model_version") != allowed[sport]:
            continue
        item = project_snapshot(row)
        game = (row.get("features") or {}).get("game") or {}
        item["home"] = str(game.get("home") or game.get("home_team") or item["home"])
        item["away"] = str(game.get("away") or game.get("away_team") or item["away"])
        result.append(item)
    return result

def _separate_candidates(table, day, sport):
    start, end = _range(day)
    try:
        query = get_supabase_client().table(table).select("*")
        date_field = "data_cutoff_at" if sport == "FOOTBALL" else "created_at"
        rows = query.gte(date_field, start).lt(date_field, end).eq("result_status", "PENDING").limit(1000).execute().data or []
    except Exception:
        logger.info("%s snapshots unavailable for market lab date=%s", sport, day)
        return []
    result = []
    for row in rows:
        if sport == "FOOTBALL":
            mapped = {**row, "sport": sport, "league": sport, "event_id": row.get("provider_match_id"),
                "home_team": row.get("home_team"), "away_team": row.get("away_team"),
                "created_at": row.get("data_cutoff_at"),
                "features": {"game": {"home": row.get("home_team"), "away": row.get("away_team")}}}
        else:
            mapped = {**row, "sport": sport, "league": sport, "event_id": row.get("match_id"),
                "home_team": row.get("player1_name"), "away_team": row.get("player2_name"),
                "home_probability": row.get("player1_probability"), "away_probability": row.get("player2_probability"),
                "features": {"game": {"home": row.get("player1_name"), "away": row.get("player2_name")}}}
        result.append(project_snapshot(mapped))
    return result

@router.get("/catalog")
def get_market_catalog(sport: str | None = Query(None)):
    return {"success": True, **catalog_for(sport)}

@router.get("/candidates")
def get_market_candidates(day: str = Query(..., alias="date")):
    try:
        date.fromisoformat(day)
        candidates = _central(day)
        candidates.extend(_separate_candidates("football_prediction_snapshots", day, "FOOTBALL"))
        candidates.extend(_separate_candidates("tennis_prediction_snapshots", day, "TENNIS"))
        candidates.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return {"success": True, "date": day, "total": len(candidates), "candidates": candidates,
            "notice": "Solo análisis pregame guardados de la fecha elegida. No necesitas cuotas para ver proyecciones."}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="La fecha debe tener formato YYYY-MM-DD.") from exc
    except Exception as exc:
        logger.exception("Market lab candidate loading failed for %s", day)
        raise HTTPException(status_code=502, detail="No se pudieron cargar los análisis guardados para el Laboratorio de Mercados.") from exc

@router.get("/projection/{snapshot_id}")
def get_market_projection(snapshot_id: str):
    client = get_supabase_client()
    for table in ("prediction_snapshots", "football_prediction_snapshots", "tennis_prediction_snapshots"):
        try:
            rows = client.table(table).select("*").eq("id", snapshot_id).limit(1).execute().data or []
            if rows:
                row = rows[0]
                if table == "football_prediction_snapshots":
                    row = {**row, "sport": "FOOTBALL", "league": "FOOTBALL",
                        "features": {"game": {"home": row.get("home_team"), "away": row.get("away_team")}}}
                elif table == "tennis_prediction_snapshots":
                    row = {**row, "sport": "TENNIS", "league": "TENNIS",
                        "home_probability": row.get("player1_probability"), "away_probability": row.get("player2_probability"),
                        "features": {"game": {"home": row.get("player1_name"), "away": row.get("player2_name")}}}
                return {"success": True, "projection": project_snapshot(row)}
        except Exception:
            continue
    raise HTTPException(status_code=404, detail="No se encontró el snapshot guardado.")
