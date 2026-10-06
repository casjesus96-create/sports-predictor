from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from nfl_client import (
    get_game,
    get_upcoming_games,
)

from nfl_analyzer import analyze_nfl_game

from nfl_repository import (
    save_nfl_analysis,
    settle_nfl_prediction,
    get_nfl_pending_predictions,
    get_nfl_predictions,
    get_nfl_performance,
    get_nfl_calibration,
)


router = APIRouter(
    prefix="/api/v1/nfl",
    tags=["NFL"],
)


@router.get("/games")
def nfl_games(limit: int = 20):

    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="limit debe ser mayor que 0.",
        )

    limit = min(limit, 50)

    try:

        games = get_upcoming_games(
            season=2026,
            limit=limit,
        )

        return {
            "success": True,
            "sport": "NFL",
            "season": 2026,
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
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


@router.get("/games/{game_id}")
def nfl_game(game_id: str):

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
                        "No se encontró el partido "
                        "NFL solicitado."
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


@router.get("/analyze/{game_id}")
def analyze_nfl(game_id: str):

    try:

        return analyze_nfl_game(
            game_id=game_id
        )

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


@router.post("/predict/{game_id}")
def predict_nfl(game_id: str):
    """
    Genera y GUARDA la predicción oficial NFL-1.0.0.

    El snapshot queda PENDING hasta que
    el partido termine.
    """

    try:

        analysis = analyze_nfl_game(
            game_id=game_id
        )

        if not analysis.get("success"):
            return analysis

        persistence = save_nfl_analysis(
            analysis
        )

        return {
            "success": True,
            "sport": "NFL",
            "model_version": analysis.get(
                "model_version",
                "NFL-1.0.0",
            ),
            "game_id": str(game_id),
            "prediction": analysis.get(
                "prediction"
            ),
            "data_cutoff": analysis.get(
                "data_cutoff"
            ),
            "persistence": persistence,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "NFL_PREDICTION_SAVE_ERROR"
                ),
                "message": (
                    "No fue posible generar "
                    "y guardar la predicción NFL."
                ),
                "details": str(exc),
            },
        )


@router.get("/predictions")
def nfl_predictions(
    status: str = None,
    limit: int = 100,
):

    try:

        if status:

            status = status.upper()

            if status not in {
                "PENDING",
                "SETTLED",
            }:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "status debe ser "
                        "PENDING o SETTLED."
                    ),
                )

        return {
            "success": True,
            "sport": "NFL",
            "model_version": "NFL-1.0.0",
            "predictions": get_nfl_predictions(
                result_status=status,
                limit=limit,
            ),
        }

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "NFL_PREDICTIONS_ERROR"
                ),
                "message": (
                    "No fue posible obtener "
                    "las predicciones NFL."
                ),
                "details": str(exc),
            },
        )


@router.get("/pending")
def nfl_pending():

    try:

        rows = get_nfl_pending_predictions()

        return {
            "success": True,
            "sport": "NFL",
            "model_version": "NFL-1.0.0",
            "total": len(rows),
            "predictions": rows,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": "NFL_PENDING_ERROR",
                "message": (
                    "No fue posible obtener "
                    "las predicciones pendientes."
                ),
                "details": str(exc),
            },
        )


@router.post("/settle/{game_id}")
def settle_nfl(
    game_id: str,
    prediction_id: str = None,
):
    """
    Consulta el resultado final en nflverse
    y liquida la predicción NFL PENDING.
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
                        "No se encontró el partido "
                        "NFL solicitado."
                    ),
                    "game_id": str(game_id),
                },
            )

        home_score = game.get(
            "home_score"
        )

        away_score = game.get(
            "away_score"
        )

        if (
            home_score is None
            or away_score is None
        ):

            return {
                "success": False,
                "game_id": str(game_id),
                "status": "PENDING",
                "message": (
                    "El partido todavía no tiene "
                    "marcador final. La predicción "
                    "permanece PENDING."
                ),
            }

        if float(home_score) == float(
            away_score
        ):

            return {
                "success": False,
                "game_id": str(game_id),
                "status": "UNRESOLVED",
                "message": (
                    "El marcador NFL no permite "
                    "determinar un ganador."
                ),
            }

        actual_winner = (
            game["home"]
            if float(home_score)
            > float(away_score)
            else game["away"]
        )

        settlement = settle_nfl_prediction(
            event_id=game_id,
            actual_winner=actual_winner,
            actual_home_score=int(
                home_score
            ),
            actual_away_score=int(
                away_score
            ),
            prediction_id=prediction_id,
        )

        return {
            "success": settlement.get(
                "success",
                False,
            ),
            "sport": "NFL",
            "game_id": str(game_id),
            "home": game.get("home"),
            "away": game.get("away"),
            "home_score": int(home_score),
            "away_score": int(away_score),
            "actual_winner": actual_winner,
            "settlement": settlement,
        }

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "NFL_SETTLEMENT_ERROR"
                ),
                "message": (
                    "No fue posible liquidar "
                    "la predicción NFL."
                ),
                "details": str(exc),
            },
        )


@router.post("/settle-pending")
def settle_pending_nfl():
    """
    Revisa todas las predicciones NFL PENDING.

    Liquida automáticamente las que ya
    tienen resultado final.
    """

    try:

        pending = (
            get_nfl_pending_predictions()
        )

        settled = []
        still_pending = []
        failed = []

        for prediction in pending:

            event_id = str(
                prediction.get("event_id")
            )

            try:

                game = get_game(
                    game_id=event_id,
                    season=2026,
                )

                if not game:

                    failed.append({
                        "event_id": event_id,
                        "message": (
                            "Partido no encontrado."
                        ),
                    })

                    continue

                home_score = game.get(
                    "home_score"
                )

                away_score = game.get(
                    "away_score"
                )

                if (
                    home_score is None
                    or away_score is None
                ):

                    still_pending.append({
                        "event_id": event_id,
                        "reason": (
                            "Sin marcador final."
                        ),
                    })

                    continue

                if float(home_score) == float(
                    away_score
                ):

                    failed.append({
                        "event_id": event_id,
                        "message": (
                            "No se pudo determinar "
                            "ganador."
                        ),
                    })

                    continue

                actual_winner = (
                    game["home"]
                    if float(home_score)
                    > float(away_score)
                    else game["away"]
                )

                result = settle_nfl_prediction(
                    event_id=event_id,
                    actual_winner=actual_winner,
                    actual_home_score=int(
                        home_score
                    ),
                    actual_away_score=int(
                        away_score
                    ),
                    prediction_id=prediction.get(
                        "id"
                    ),
                )

                settled.append(result)

            except Exception as exc:

                failed.append({
                    "event_id": event_id,
                    "message": str(exc),
                })

        return {
            "success": True,
            "sport": "NFL",
            "model_version": "NFL-1.0.0",
            "summary": {
                "checked": len(pending),
                "settled": len(settled),
                "still_pending": len(
                    still_pending
                ),
                "failed": len(failed),
            },
            "settled": settled,
            "still_pending": still_pending,
            "failed": failed,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "NFL_SETTLE_PENDING_ERROR"
                ),
                "message": (
                    "No fue posible revisar "
                    "las predicciones NFL pendientes."
                ),
                "details": str(exc),
            },
        )


@router.get("/performance")
def nfl_performance():

    try:

        return get_nfl_performance()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "NFL_PERFORMANCE_ERROR"
                ),
                "message": (
                    "No fue posible calcular "
                    "el rendimiento NFL."
                ),
                "details": str(exc),
            },
        )


@router.get("/calibration")
def nfl_calibration(
    minimum_sample: int = 30,
):
    """
    Muestra calibración de confianza.

    No modifica el modelo.
    """

    if minimum_sample < 1:

        raise HTTPException(
            status_code=400,
            detail=(
                "minimum_sample debe "
                "ser mayor que 0."
            ),
        )

    try:

        return get_nfl_calibration(
            minimum_sample=minimum_sample
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "NFL_CALIBRATION_ERROR"
                ),
                "message": (
                    "No fue posible calcular "
                    "la calibración NFL."
                ),
                "details": str(exc),
            },
        )


@router.get("/status")
def nfl_status():

    return {
        "success": True,
        "sport": "NFL",
        "season": 2026,
        "model_version": "NFL-1.0.0",
        "status": "active",
        "prediction_persistence": "active",
        "settlement": "active",
        "calibration": "active",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }
