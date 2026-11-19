"""Read-only NHL data endpoints; no prediction model is active."""
import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from nhl_client import NHLDataError, get_boxscore, get_games

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
        return {
            "success": True,
            "sport": "NHL",
            "date": selected_date,
            "source": "NHL public web feed",
            "model_status": "not_started",
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
    from nhl_client import get_team_season_schedule

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
