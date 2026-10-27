"""Read-only cross-sport market laboratory for saved pregame snapshots."""
from __future__ import annotations
import logging
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from market_lab_engine import catalog_for, normalize_sport, project_snapshot
from repository import get_supabase_client
from batter_hit_projection import build_live_batter_hit_projections

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


@router.get("/mlb/live-batters/{game_id}")
def get_live_mlb_batter_report(game_id: str):
    """Read-only live MLB boxscore for Market Lab; never runs or saves the official pregame model."""
    import requests
    from datetime import datetime, timezone

    if not game_id.isdigit():
        raise HTTPException(status_code=400, detail="El ID del partido MLB debe ser numérico.")

    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live"
    try:
        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Sports-Predictor/1.0", "Accept": "application/json"},
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="MLB no encontró el partido indicado.")
        response.raise_for_status()
        feed = response.json()
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.warning("Live MLB boxscore request failed for game_id=%s: %s", game_id, type(exc).__name__)
        raise HTTPException(status_code=502, detail="No se pudo consultar el marcador en vivo de MLB.") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="MLB devolvió una respuesta que no se pudo interpretar.") from exc

    game_data = feed.get("gameData") or {}
    live_data = feed.get("liveData") or {}
    status_data = game_data.get("status") or {}
    boxscore = live_data.get("boxscore") or {}
    teams_data = boxscore.get("teams") or {}
    linescore = live_data.get("linescore") or {}
    game_teams = game_data.get("teams") or {}
    probable_pitchers = game_data.get("probablePitchers") or {}
    defense = linescore.get("defense") or {}
    active_pitcher = defense.get("pitcher") or {}
    active_pitcher_id = active_pitcher.get("id")
    active_pitcher_name = active_pitcher.get("fullName") or active_pitcher.get("name")
    inning_half = str(linescore.get("inningState") or "").lower()
    active_batting_side = "away" if inning_half == "top" else ("home" if inning_half == "bottom" else None)
    result_teams = []

    for side in ("away", "home"):
        team_box = teams_data.get(side) or {}
        players = team_box.get("players") or {}
        batting_order = team_box.get("battingOrder") or []
        hitters = []
        for order, raw_player_id in enumerate(batting_order, start=1):
            try:
                player_id = int(raw_player_id)
            except (TypeError, ValueError):
                continue
            player = players.get(f"ID{player_id}") or players.get(str(player_id)) or {}
            person = player.get("person") or {}
            stats = ((player.get("stats") or {}).get("batting") or {})
            name = person.get("fullName") or person.get("name")
            if not name:
                continue
            hits = stats.get("hits")
            at_bats = stats.get("atBats")
            try:
                hits = int(hits) if hits is not None else None
            except (TypeError, ValueError):
                hits = None
            try:
                at_bats = int(at_bats) if at_bats is not None else None
            except (TypeError, ValueError):
                at_bats = None
            hitters.append({
                "player_id": player_id,
                "player_name": name,
                "batting_order": order,
                "position": (player.get("position") or {}).get("abbreviation"),
                "hits_in_game": hits,
                "at_bats_in_game": at_bats,
                "game_avg": round(hits / at_bats, 3) if hits is not None and at_bats else None,
            })
        team_info = game_teams.get(side) or {}
        opposing_side = "home" if side == "away" else "away"
        pitcher = probable_pitchers.get(opposing_side) or {}
        pitcher_id = pitcher.get("id")
        pitcher_name = pitcher.get("fullName") or pitcher.get("name")
        pitcher_source = "abridor previsto" if pitcher_id else None
        # In a live half-inning, prefer the actual defensive pitcher for the team currently batting.
        if side == active_batting_side and active_pitcher_id:
            pitcher_id = active_pitcher_id
            pitcher_name = active_pitcher_name or pitcher_name
            pitcher_source = "pitcher actual en juego"
        result_teams.append({
            "side": side,
            "team_id": team_info.get("id"),
            "team_name": team_info.get("name") or team_box.get("team", {}).get("name") or side,
            "lineup_available": bool(batting_order),
            "opposing_pitcher_id": pitcher_id,
            "opposing_pitcher_name": pitcher_name,
            "pitcher_source": pitcher_source,
            "hitters": hitters,
        })

    game_datetime = (game_data.get("datetime") or {}).get("originalDate") or (game_data.get("datetime") or {}).get("date") or ""
    try:
        season = int(str(game_datetime)[:4])
    except (TypeError, ValueError):
        from datetime import datetime
        season = datetime.now().year
    live_projection = build_live_batter_hit_projections(
        result_teams,
        season=season,
        current_inning=linescore.get("currentInning") or 1,
        inning_state=linescore.get("inningState") or "Top",
        game_status=status_data.get("abstractGameState") or status_data.get("detailedState") or "Warmup",
    )

    return {
        "success": True,
        "report_type": "live_boxscore_context",
        "event_id": str(game_id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "game_status": status_data.get("abstractGameState"),
        "detailed_status": status_data.get("detailedState"),
        "home_score": (linescore.get("teams") or {}).get("home", {}).get("runs"),
        "away_score": (linescore.get("teams") or {}).get("away", {}).get("runs"),
        "current_inning": linescore.get("currentInning"),
        "inning_state": linescore.get("inningState"),
        "outs": linescore.get("outs"),
        "teams": result_teams,
        "probabilities_available": bool(live_projection.get("available")),
        "live_hit_projections": live_projection,
        "notice": (
            "Contexto en vivo MLB con proyección experimental 1+ hit hasta el final. Usa AVG de temporada, oportunidades restantes y, cuando está disponible, historial directo ante el pitcher identificado con ajuste conservador. "
            "No está calibrada con backtesting y no modifica el análisis oficial ni el historial."
        ),
    }
