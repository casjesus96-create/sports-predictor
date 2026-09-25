from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
import requests
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from analyzer import analyze_mlb_game
from repository import (
    save_prediction,
    save_analysis,
    settle_prediction,
    get_performance,
    get_predictions,
    get_supabase_client,
    reconcile_settled_prediction,
)


app = FastAPI(
    title="Sports Predictor API",
    version="2.0.0",
    description=(
        "API de proyecciones deportivas con análisis MLB, "
        "forma histórica, análisis diario y liquidación automática."
    ),
)


MLB_API = "https://statsapi.mlb.com/api/v1"

MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0"
}

CURRENT_MODEL_VERSION = "2.0.0-matchup"


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "sports-predictor",
        "version": "2.0.0",
        "model_version": CURRENT_MODEL_VERSION,
    }


# =========================================================
# MLB GAMES
# =========================================================

@app.get("/api/v1/mlb/games")
def get_mlb_games(
    date: str = None
):
    """
    Obtiene los partidos MLB de una fecha determinada.

    Ejemplo:

    /api/v1/mlb/games?date=2026-09-22

    Si no se proporciona una fecha, utiliza la fecha
    actual en UTC.
    """

    try:

        # -------------------------------------------------
        # 1. Determinar fecha
        # -------------------------------------------------

        if not date:
            date = datetime.now(
                timezone.utc
            ).strftime("%Y-%m-%d")

        # -------------------------------------------------
        # 2. Validar formato de fecha
        # -------------------------------------------------

        try:

            datetime.strptime(
                date,
                "%Y-%m-%d"
            )

        except ValueError:

            raise HTTPException(
                status_code=400,
                detail=(
                    "La fecha debe utilizar el formato "
                    "YYYY-MM-DD. Ejemplo: 2026-09-22"
                ),
            )

        # -------------------------------------------------
        # 3. Consultar MLB
        # -------------------------------------------------

        url = f"{MLB_API}/schedule"

        params = {
            "sportId": 1,
            "date": date,
            "hydrate": (
                "probablePitcher,"
                "team,"
                "venue"
            ),
        }

        response = requests.get(
            url,
            params=params,
            timeout=20,
            headers=MLB_HEADERS,
        )

        response.raise_for_status()

        data = response.json()

        # -------------------------------------------------
        # 4. Procesar partidos
        # -------------------------------------------------

        games = []

        for date_block in data.get(
            "dates",
            []
        ):

            for game in date_block.get(
                "games",
                []
            ):

                game_pk = game.get(
                    "gamePk"
                )

                teams = game.get(
                    "teams",
                    {}
                )

                home = teams.get(
                    "home",
                    {}
                )

                away = teams.get(
                    "away",
                    {}
                )

                home_team = home.get(
                    "team",
                    {}
                )

                away_team = away.get(
                    "team",
                    {}
                )

                home_pitcher = (
                    home.get(
                        "probablePitcher",
                        {}
                    )
                )

                away_pitcher = (
                    away.get(
                        "probablePitcher",
                        {}
                    )
                )

                status = game.get(
                    "status",
                    {}
                )

                games.append(
                    {
                        "game_id": (
                            str(game_pk)
                            if game_pk is not None
                            else None
                        ),

                        "date": game.get(
                            "gameDate"
                        ),

                        "status": status.get(
                            "abstractGameState"
                        ),

                        "detailed_status": status.get(
                            "detailedState"
                        ),

                        "venue": (
                            game
                            .get(
                                "venue",
                                {}
                            )
                            .get(
                                "name"
                            )
                        ),

                        "home": {
                            "id": home_team.get(
                                "id"
                            ),
                            "name": home_team.get(
                                "name"
                            ),
                            "probable_pitcher": {
                                "id": home_pitcher.get(
                                    "id"
                                ),
                                "name": home_pitcher.get(
                                    "fullName"
                                ),
                            },
                        },

                        "away": {
                            "id": away_team.get(
                                "id"
                            ),
                            "name": away_team.get(
                                "name"
                            ),
                            "probable_pitcher": {
                                "id": away_pitcher.get(
                                    "id"
                                ),
                                "name": away_pitcher.get(
                                    "fullName"
                                ),
                            },
                        },
                    }
                )

        return {
            "success": True,
            "date": date,
            "total": len(games),
            "games": games,
        }

    except HTTPException:
        raise

    except requests.exceptions.HTTPError as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "error": "MLB_API_HTTP_ERROR",
                "message": (
                    "MLB respondió con un error HTTP."
                ),
                "details": str(exc),
            },
        )

    except requests.exceptions.RequestException as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "error": "MLB_API_CONNECTION_ERROR",
                "message": (
                    "No fue posible comunicarse "
                    "con la API de MLB."
                ),
                "details": str(exc),
            },
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": "MLB_GAMES_ERROR",
                "message": (
                    "Error obteniendo los partidos MLB."
                ),
                "details": str(exc),
            },
        )


# =========================================================
# ANALYZE DAY
# =========================================================

@app.get("/api/v1/mlb/analyze-day")
def analyze_mlb_day(
    date: str = None
):
    """
    Analiza automáticamente todos los partidos MLB
    de una fecha determinada.

    Ejemplo:

    /api/v1/mlb/analyze-day?date=2026-09-22

    El endpoint:

    1. Obtiene los partidos MLB.
    2. Analiza cada partido.
    3. Guarda las predicciones en Supabase.
    4. Evita duplicar una predicción PENDING
       de la misma versión del modelo.
    5. Continúa aunque un partido individual falle.
    """

    try:

        if not date:
            date = datetime.now(
                timezone.utc
            ).strftime("%Y-%m-%d")

        try:

            datetime.strptime(
                date,
                "%Y-%m-%d"
            )

        except ValueError:

            raise HTTPException(
                status_code=400,
                detail=(
                    "La fecha debe utilizar el formato "
                    "YYYY-MM-DD. Ejemplo: 2026-09-22"
                ),
            )

        games_response = get_mlb_games(
            date=date
        )

        games = games_response.get(
            "games",
            []
        )

        total_games = len(games)

        predictions = []
        skipped = []
        failed = []

        analyzed_count = 0
        skipped_count = 0
        failed_count = 0

        supabase = get_supabase_client()

        for game in games:

            event_id = game.get(
                "game_id"
            )

            home_name = (
                game
                .get("home", {})
                .get("name")
            )

            away_name = (
                game
                .get("away", {})
                .get("name")
            )

            game_status = game.get(
                "status"
            )

            detailed_status = game.get(
                "detailed_status"
            )

            # -------------------------------------------------
            # Validar game_id
            # -------------------------------------------------

            if not event_id:

                failed_count += 1

                failed.append(
                    {
                        "event_id": None,
                        "home": home_name,
                        "away": away_name,
                        "error": (
                            "El partido no tiene game_id."
                        ),
                    }
                )

                continue

            # -------------------------------------------------
            # No analizar partidos Final
            # -------------------------------------------------

            if game_status == "Final":

                skipped_count += 1

                skipped.append(
                    {
                        "event_id": event_id,
                        "home": home_name,
                        "away": away_name,
                        "status": game_status,
                        "detailed_status": detailed_status,
                        "reason": (
                            "El partido ya está Final."
                        ),
                    }
                )

                continue

            # -------------------------------------------------
            # Buscar predicción PENDING existente
            # -------------------------------------------------

            try:

                existing_response = (
                    supabase
                    .table(
                        "prediction_snapshots"
                    )
                    .select("*")
                    .eq(
                        "event_id",
                        str(event_id)
                    )
                    .eq(
                        "model_version",
                        CURRENT_MODEL_VERSION
                    )
                    .eq(
                        "result_status",
                        "PENDING"
                    )
                    .order(
                        "created_at",
                        desc=True
                    )
                    .limit(1)
                    .execute()
                )

                existing_rows = (
                    existing_response.data
                    or []
                )

            except Exception:

                existing_rows = []

            # -------------------------------------------------
            # Si ya existe, no duplicar
            # -------------------------------------------------

            if existing_rows:

                existing = existing_rows[0]

                features = (
                    existing.get(
                        "features"
                    )
                    or {}
                )

                existing_game = (
                    features.get(
                        "game"
                    )
                    or {}
                )

                predicted_winner = (
                    features.get(
                        "predicted_winner"
                    )
                )

                skipped_count += 1

                skipped.append(
                    {
                        "event_id": event_id,
                        "home": (
                            existing_game.get(
                                "home"
                            )
                            or home_name
                        ),
                        "away": (
                            existing_game.get(
                                "away"
                            )
                            or away_name
                        ),
                        "reason": (
                            "Ya existe una predicción "
                            "PENDING para este partido "
                            "y esta versión del modelo."
                        ),
                        "prediction_id": existing.get(
                            "id"
                        ),
                        "predicted_winner": predicted_winner,
                        "home_probability": existing.get(
                            "home_probability"
                        ),
                        "away_probability": existing.get(
                            "away_probability"
                        ),
                        "confidence": existing.get(
                            "confidence"
                        ),
                    }
                )

                continue

            # -------------------------------------------------
            # Analizar partido
            # -------------------------------------------------

            try:

                analysis = analyze_mlb_game(
                    str(event_id)
                )

                if not analysis.get(
                    "success"
                ):

                    failed_count += 1

                    failed.append(
                        {
                            "event_id": event_id,
                            "home": home_name,
                            "away": away_name,
                            "error": (
                                analysis.get(
                                    "message"
                                )
                                or analysis.get(
                                    "error"
                                )
                                or "El análisis falló."
                            ),
                            "analysis": analysis,
                        }
                    )

                    continue

                # -------------------------------------------------
                # Guardar análisis
                # -------------------------------------------------

                persistence = save_analysis(
                    analysis
                )

                prediction = (
                    analysis.get(
                        "prediction",
                        {}
                    )
                )

                analyzed_count += 1

                predictions.append(
                    {
                        "event_id": str(
                            event_id
                        ),
                        "home": home_name,
                        "away": away_name,
                        "status": game_status,
                        "detailed_status": detailed_status,
                        "game_date": game.get(
                            "date"
                        ),
                        "venue": game.get(
                            "venue"
                        ),
                        "predicted_winner": prediction.get(
                            "winner"
                        ),
                        "home_probability": prediction.get(
                            "home_probability"
                        ),
                        "away_probability": prediction.get(
                            "away_probability"
                        ),
                        "confidence": prediction.get(
                            "confidence"
                        ),
                        "data_quality": prediction.get(
                            "data_quality"
                        ),
                        "model_version": analysis.get(
                            "model_version",
                            CURRENT_MODEL_VERSION
                        ),
                        "saved": (
                            persistence.get(
                                "saved",
                                False
                            )
                            if isinstance(
                                persistence,
                                dict
                            )
                            else False
                        ),
                        "prediction_id": (
                            (
                                persistence
                                .get("data", [{}])[0]
                                .get("id")
                            )
                            if isinstance(
                                persistence,
                                dict
                            )
                            and persistence.get(
                                "data"
                            )
                            else None
                        ),
                    }
                )

            except Exception as exc:

                failed_count += 1

                failed.append(
                    {
                        "event_id": event_id,
                        "home": home_name,
                        "away": away_name,
                        "error": str(exc),
                    }
                )

                continue

        # -------------------------------------------------
        # Resultado final del análisis diario
        # -------------------------------------------------

        return {
            "success": True,
            "date": date,
            "model_version": CURRENT_MODEL_VERSION,
            "summary": {
                "total_games": total_games,
                "analyzed": analyzed_count,
                "skipped": skipped_count,
                "failed": failed_count,
            },
            "predictions": predictions,
            "skipped": skipped,
            "failed": failed,
        }

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": "MLB_ANALYZE_DAY_ERROR",
                "message": (
                    "Error ejecutando el análisis "
                    "automático de la jornada MLB."
                ),
                "details": str(exc),
            },
        )


# =========================================================
# EXPERIMENTAL PREDICTION
# =========================================================

@app.post("/api/v1/predictions/experimental")
def create_experimental_prediction(
    event_id: str,
    sport: str = "baseball",
    league: str = "MLB",
):
    try:

        result = save_prediction(
            event_id=event_id,
            sport=sport,
            league=league,
            model_version="MLB-Baseline-0.1",
            home_probability=0.53743,
            away_probability=0.46257,
            confidence="Inicial",
            data_quality=72,
            features={
                "source": "experimental",
            },
        )

        return {
            "success": True,
            "saved": True,
            "data": result,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# =========================================================
# ANALYZE GAME
# =========================================================

@app.post("/api/v1/analyze")
def analyze_game(
    event_id: str
):
    """
    Analiza un partido MLB utilizando el modelo actual.

    El modelo actual es 2.0.0-matchup.
    """

    try:

        analysis = analyze_mlb_game(
            event_id
        )

        if not analysis.get(
            "success"
        ):

            return analysis

        persistence = save_analysis(
            analysis
        )

        analysis["persistence"] = (
            persistence
        )

        return analysis

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# =========================================================
# SETTLE GAME
# =========================================================

@app.post("/api/v1/settle/{event_id}")
def settle_game(
    event_id: str,
    prediction_id: str = None,
):
    try:

        event_id = str(
            event_id
        )

        # -------------------------------------------------
        # Consultar calendario MLB
        # -------------------------------------------------

        schedule_url = (
            f"{MLB_API}/schedule"
        )

        schedule_params = {
            "sportId": 1,
            "gamePk": event_id,
            "hydrate": (
                "probablePitcher,"
                "team,"
                "venue"
            ),
        }

        schedule_response = requests.get(
            schedule_url,
            params=schedule_params,
            timeout=20,
            headers=MLB_HEADERS,
        )

        if schedule_response.status_code == 404:

            return {
                "success": False,
                "event_id": event_id,
                "status": "NOT_FOUND",
                "message": (
                    "MLB no encontró un partido "
                    "con este event_id. "
                    "Verifica que el gamePk sea correcto."
                ),
            }

        schedule_response.raise_for_status()

        schedule_data = (
            schedule_response.json()
        )

        scheduled_games = []

        for date_block in schedule_data.get(
            "dates",
            []
        ):

            scheduled_games.extend(
                date_block.get(
                    "games",
                    []
                )
            )

        # -------------------------------------------------
        # Buscar partido
        # -------------------------------------------------

        target_game = None

        for game in scheduled_games:

            if (
                str(game.get("gamePk"))
                == event_id
            ):

                target_game = game

                break

        if target_game is None:

            return {
                "success": False,
                "event_id": event_id,
                "status": "NOT_FOUND",
                "message": (
                    "El event_id no aparece "
                    "en el calendario actual de MLB. "
                    "Puede tratarse de un gamePk "
                    "incorrecto o de un partido que MLB "
                    "ya no expone mediante este endpoint."
                ),
            }

        # -------------------------------------------------
        # Estado del partido
        # -------------------------------------------------

        game_status = (
            target_game
            .get(
                "status",
                {}
            )
            .get(
                "abstractGameState"
            )
        )

        detailed_state = (
            target_game
            .get(
                "status",
                {}
            )
            .get(
                "detailedState"
            )
        )

        teams = target_game.get(
            "teams",
            {}
        )

        # -------------------------------------------------
        # Equipo local
        # -------------------------------------------------

        home_team = (
            teams
            .get(
                "home",
                {}
            )
            .get(
                "team",
                {}
            )
            .get(
                "name"
            )
        )

        # -------------------------------------------------
        # Equipo visitante
        # -------------------------------------------------

        away_team = (
            teams
            .get(
                "away",
                {}
            )
            .get(
                "team",
                {}
            )
            .get(
                "name"
            )
        )

        # -------------------------------------------------
        # Marcadores
        # -------------------------------------------------

        home_score = (
            teams
            .get(
                "home",
                {}
            )
            .get(
                "score"
            )
        )

        away_score = (
            teams
            .get(
                "away",
                {}
            )
            .get(
                "score"
            )
        )

        # -------------------------------------------------
        # Partido todavía no terminado
        # -------------------------------------------------

        if game_status != "Final":

            return {
                "success": False,
                "event_id": event_id,
                "status": game_status,
                "detailed_status": detailed_state,
                "home": home_team,
                "away": away_team,
                "home_score": home_score,
                "away_score": away_score,
                "message": (
                    "El partido todavía no ha terminado. "
                    "La predicción permanece PENDING."
                ),
            }

        # -------------------------------------------------
        # Verificar marcador
        # -------------------------------------------------

        if (
            home_score is None
            or away_score is None
        ):

            return {
                "success": False,
                "event_id": event_id,
                "status": "Final",
                "home": home_team,
                "away": away_team,
                "message": (
                    "MLB marca el partido como Final, "
                    "pero todavía no proporcionó "
                    "el marcador completo."
                ),
            }

        home_score = int(
            home_score
        )

        away_score = int(
            away_score
        )

        # -------------------------------------------------
        # Determinar ganador
        # -------------------------------------------------

        if home_score > away_score:

            actual_winner = home_team

        elif away_score > home_score:

            actual_winner = away_team

        else:

            return {
                "success": False,
                "event_id": event_id,
                "status": "Final",
                "home": home_team,
                "away": away_team,
                "home_score": home_score,
                "away_score": away_score,
                "message": (
                    "El marcador recibido no permite "
                    "determinar un ganador."
                ),
            }

        # -------------------------------------------------
        # Liquidar predicción
        # -------------------------------------------------

        settlement = settle_prediction(
            event_id=event_id,
            actual_winner=actual_winner,
            actual_home_score=home_score,
            actual_away_score=away_score,
            prediction_id=prediction_id,
            model_version=CURRENT_MODEL_VERSION,
        )

        # -------------------------------------------------
        # Respuesta
        # -------------------------------------------------

        return {
            "success": True,
            "event_id": event_id,
            "status": "Final",
            "home": home_team,
            "away": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "actual_winner": actual_winner,
            "prediction_result": settlement.get(
                "prediction_result"
            ),
            "settled_at": settlement.get(
                "settled_at"
            ),
            "settlement": settlement,
        }

    except requests.exceptions.HTTPError as exc:

        return {
            "success": False,
            "event_id": str(
                event_id
            ),
            "status": "MLB_API_ERROR",
            "message": (
                "MLB respondió con un error HTTP."
            ),
            "details": str(exc),
        }

    except requests.exceptions.RequestException as exc:

        return {
            "success": False,
            "event_id": str(
                event_id
            ),
            "status": "MLB_CONNECTION_ERROR",
            "message": (
                "No fue posible comunicarse "
                "con MLB."
            ),
            "details": str(exc),
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.post("/api/v1/reconcile/{event_id}")
def reconcile(event_id: str):
    try:
        return reconcile_settled_prediction(event_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "RECONCILE_ERROR",
                "message": "No fue posible reconciliar el resultado.",
                "details": str(exc),
            },
        )


# =========================================================
# PERFORMANCE
# =========================================================

@app.get("/api/v1/performance")
def performance():

    try:

        return get_performance()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "Error obteniendo "
                    "rendimiento del modelo"
                ),
                "details": str(exc),
            },
        )


# =========================================================
# PREDICTIONS
# =========================================================

@app.get("/api/v1/predictions")
def predictions():

    try:

        return get_predictions()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "Error obteniendo "
                    "predicciones"
                ),
                "details": str(exc),
            },
        )


# =========================================================
# FRONTEND WEB
# =========================================================

FRONTEND_DIST = Path(__file__).resolve().parent / "dist"

if FRONTEND_DIST.exists():

    @app.get("/", include_in_schema=False)
    def frontend_index():
        return FileResponse(FRONTEND_DIST / "index.html")

    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIST), html=True),
        name="frontend",
    )
