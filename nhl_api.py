"""Read-only NHL data endpoints with an isolated, research-only Elo projection."""
import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from nhl_client import NHLDataError, get_boxscore, get_games, get_team_season_schedule
from nhl_prediction_model import predict_winner
from nhl_team_identity_registry import resolve_team_identity
from repository import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/nhl", tags=["NHL"])


@router.get("/games")
def nhl_games(date_value: str | None = Query(None, alias="date")):
    """Return the NHL scoreboard for a single UTC calendar date."""
    try:
        selected_date = date_value or datetime.now(timezone.utc).date().isoformat()
        try:
            date.fromisoformat(selected_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="date debe usar el formato YYYY-MM-DD.") from exc
        games = get_games(selected_date)
        archive_rows = []
        archive_status = "AVAILABLE"
        try:
            supabase = get_supabase_client()
            offset = 0
            page_size = 1000
            while True:
                page = (
                    supabase.table("nhl_game_archive")
                    .select("*")
                    .eq("training_eligible", True)
                    .eq("source_terms_status", "reviewed")
                    .order("game_date")
                    .order("game_id")
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                rows = page.data or []
                archive_rows.extend(rows)
                if len(rows) < page_size:
                    break
                offset += page_size
        except Exception as exc:
            archive_status = "ARCHIVE_UNAVAILABLE"
            logger.warning("NHL approved archive unavailable: %s", exc)

        for game in games:
            game_type = game.get("game_type")
            season_start = int(game["game_date"][:4]) if int(game["game_date"][5:7]) >= 7 else int(game["game_date"][:4]) - 1
            season = f"{season_start}-{season_start + 1}"
            home_key = resolve_team_identity(season, (game.get("home") or {}).get("abbreviation"))
            away_key = resolve_team_identity(season, (game.get("away") or {}).get("abbreviation"))
            if archive_status != "AVAILABLE":
                game["research_prediction"] = {
                    "status": archive_status,
                    "message": "No fue posible consultar el archivo histórico propio; no se publica una probabilidad.",
                }
            elif not home_key or not away_key or game_type not in (2, 3):
                game["research_prediction"] = {
                    "status": "IDENTITY_OR_GAME_TYPE_UNAVAILABLE",
                    "message": "No hay identidad canónica o tipo de partido confirmado para este cálculo.",
                }
            else:
                try:
                    game["research_prediction"] = predict_winner(
                        archive_rows,
                        home_key,
                        away_key,
                        as_of_date=game["game_date"],
                        game_type=game_type,
                    )
                except (TypeError, ValueError) as exc:
                    logger.warning("NHL research prediction skipped for game %s: %s", game.get("game_id"), exc)
                    game["research_prediction"] = {
                        "status": "RESEARCH_CALCULATION_ERROR",
                        "message": "No se pudo calcular la proyección experimental para este partido.",
                    }
        return {
            "success": True,
            "sport": "NHL",
            "date": selected_date,
            "source": "NHL public web feed",
            "model_status": "research_only",
            "research_model_version": "NHL-ELO-RESEARCH-0.1.0",
            "research_archive_status": archive_status,
            "total": len(games),
            "games": games,
        }
    except HTTPException:
        raise
    except NHLDataError as exc:
        logger.warning("NHL scoreboard unavailable: %s", exc)
        raise HTTPException(status_code=502, detail={"error": "NHL_SOURCE_ERROR", "message": str(exc)}) from exc


@router.get("/history/team-schedule/{team}/{season}")
def nhl_team_season_schedule(team: str, season: str):
    """Return one team's historical season schedule without persisting it."""
    try:
        return get_team_season_schedule(team, season)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NHLDataError as exc:
        logger.warning("NHL season schedule unavailable for %s %s: %s", team, season, exc)
        raise HTTPException(status_code=502, detail={"error": "NHL_HISTORY_SOURCE_ERROR", "message": str(exc)}) from exc


@router.get("/games/{game_id}/boxscore")
def nhl_game_boxscore(game_id: str):
    """Return normalized player and goalie boxscore statistics for one game."""
    try:
        return get_boxscore(game_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NHLDataError as exc:
        logger.warning("NHL boxscore unavailable for game %s: %s", game_id, exc)
        raise HTTPException(status_code=502, detail={"error": "NHL_BOXSCORE_ERROR", "message": str(exc)}) from exc
