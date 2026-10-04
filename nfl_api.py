from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from nfl_client import (
    get_game,
    get_upcoming_games,
)
from nfl_analyzer import analyze_nfl_game


router = APIRouter(
    prefix="/api/v1/nfl",
    tags=["NFL"],
)


# =========================================================
# UTILIDADES
# =========================================================

def validate_date(value):
    """
    Valida una fecha YYYY-MM-DD.
    """

    try:
        datetime.strptime(
            value,
            "%Y-%m-%d",
        )

        return True

    except ValueError:
        return False


# =========================================================
# NFL GAMES
# =========================================================

@router.get("/games")
def nfl_games(
    limit: int = 20,
):
    """
    Devuelve los próximos partidos NFL.

    Ejemplo:

    /api/v1/nfl/games?limit=10
    """

    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="limit debe ser mayor que 0.",
        )

    if limit > 50:
        limit = 50

    try:

        games = get_upcoming_games(
            season=2026,
            limit=limit,
        )

        return {
            "success": True,
            "sport": "NFL",
            "season": 2026,
            "generated_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "total": len(games),
            "games": games,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "error": "NFL_GAMES_ERROR",
                "message": (
                    "No fue posible obtener "
                    "los partidos NFL."
                ),
                "details": str(exc),
            },
        )


# =========================================================
# NFL GAME
# =========================================================

@router.get("/games/{game_id}")
def nfl_game(
    game_id: str,
):
    """
    Devuelve la información de un partido NFL.

    Ejemplo:

    /api/v1/nfl/games/2026_01_KC_LAC
    """

    try:

        game = get_game(
            game_id=game_id,
            season=2026,
        )

        if not game:

            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NFL_GAME_NOT_FOUND",
                    "message": (
                        "No se encontró el "
                        "partido NFL solicitado."
                    ),
                    "game_id": str(game_id),
                },
            )

        return {
            "success": True,
            "sport": "NFL",
            "model_version": "NFL-1.0.0",
            "game": game,
        }

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_GAME_ERROR",
                "message": (
                    "Error obteniendo "
                    "el partido NFL."
                ),
                "details": str(exc),
            },
        )


# =========================================================
# NFL ANALYZE
# =========================================================

@router.get("/analyze/{game_id}")
def analyze_nfl(
    game_id: str,
):
    """
    Ejecuta la proyección pregame NFL.

    IMPORTANTE:

    El análisis solamente utiliza información
    disponible antes del kickoff.

    No guarda todavía la predicción en Supabase.
    Primero validaremos el motor con partidos reales.
    """

    try:

        analysis = analyze_nfl_game(
            game_id=game_id,
        )

        if not analysis.get(
            "success",
            False,
        ):

            return analysis

        return analysis

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_ANALYSIS_ERROR",
                "message": (
                    "Error ejecutando "
                    "el análisis NFL."
                ),
                "details": str(exc),
            },
        )


# =========================================================
# NFL STATUS
# =========================================================

@router.get("/status")
def nfl_status():
    """
    Estado del motor NFL.
    """

    return {
        "success": True,
        "sport": "NFL",
        "season": 2026,
        "model_version": "NFL-1.0.0",
        "status": "active",
        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    }
