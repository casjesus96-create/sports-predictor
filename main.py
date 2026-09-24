from datetime import datetime, timezone
from pathlib import Path

import requests

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from analyzer import analyze_mlb_game

from repository import (
    save_prediction,
    save_analysis,
    settle_prediction,
    get_performance,
    get_predictions,
    get_supabase_client,
)


# =========================================================
# APPLICATION
# =========================================================

app = FastAPI(
    title="Sports Predictor API",
    version="1.4.0",
    description=(
        "API de proyecciones deportivas con análisis MLB, "
        "forma histórica, análisis diario, marcadores, "
        "liquidación y reparación de resultados."
    ),
)


# =========================================================
# CONFIGURATION
# =========================================================

MLB_API = "https://statsapi.mlb.com/api/v1"

MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0"
}

CURRENT_MODEL_VERSION = "1.2.0-form"


# =========================================================
# FRONTEND PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

FRONTEND_DIST = BASE_DIR / "dist"

FRONTEND_INDEX = FRONTEND_DIST / "index.html"

FRONTEND_ASSETS = FRONTEND_DIST / "assets"


# =========================================================
# HELPERS
# =========================================================

def validate_date(date: str):
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


def get_mlb_schedule_game(event_id: str):
    """
    Obtiene un partido específico desde MLB.
    """

    event_id = str(event_id)

    url = f"{MLB_API}/schedule"

    params = {
        "sportId": 1,
        "gamePk": event_id,
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

    for date_block in data.get(
        "dates",
        []
    ):

        for game in date_block.get(
            "games",
            []
        ):

            if str(
                game.get("gamePk")
            ) == event_id:

                return game

    return None


def extract_game_result(game):
    """
    Extrae estado, equipos y marcador de un
    partido MLB.
    """

    if not game:
        return None

    status = game.get(
        "status",
        {}
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

    home_team = (
        home
        .get("team", {})
        .get("name")
    )

    away_team = (
        away
        .get("team", {})
        .get("name")
    )

    home_score = home.get(
        "score"
    )

    away_score = away.get(
        "score"
    )

    game_status = status.get(
        "abstractGameState"
    )

    detailed_status = status.get(
        "detailedState"
    )

    actual_winner = None

    if (
        game_status == "Final"
        and home_score is not None
        and away_score is not None
    ):

        try:

            home_score_int = int(
                home_score
            )

            away_score_int = int(
                away_score
            )

            if home_score_int > away_score_int:

                actual_winner = home_team

            elif away_score_int > home_score_int:

                actual_winner = away_team

        except (
            TypeError,
            ValueError
        ):

            pass

    return {
        "event_id": str(
            game.get("gamePk")
        ),
        "status": game_status,
        "detailed_status": detailed_status,
        "home": home_team,
        "away": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "actual_winner": actual_winner,
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "service": "sports-predictor",
        "version": "1.4.0",
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
    Obtiene los partidos MLB de una fecha.

    También devuelve los marcadores cuando MLB
    ya los tiene disponibles.
    """

    try:

        # -------------------------------------------------
        # Fecha
        # -------------------------------------------------

        if not date:

            date = datetime.now(
                timezone.utc
            ).strftime("%Y-%m-%d")

        validate_date(
            date
        )

        # -------------------------------------------------
        # MLB
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

                home_score = home.get(
                    "score"
                )

                away_score = away.get(
                    "score"
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

                            "score": home_score,

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

                            "score": away_score,

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

    try:

        if not date:

            date = datetime.now(
                timezone.utc
            ).strftime("%Y-%m-%d")

        validate_date(
            date
        )

        games_response = get_mlb_games(
            date=date
        )

        games = games_response.get(
            "games",
            []
        )

        total_games = len(
            games
        )

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
            # No crear predicciones para Final
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
            # Buscar PENDING
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
                            "PENDING para este partido."
                        ),
                        "prediction_id": existing.get(
                            "id"
                        ),
                    }
                )

                continue

            # -------------------------------------------------
            # Analizar
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
                        }
                    )

                    continue

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
    event_id: str
):

    try:

        event_id = str(
            event_id
        )

        target_game = get_mlb_schedule_game(
            event_id
        )

        if target_game is None:

            return {
                "success": False,
                "event_id": event_id,
                "status": "NOT_FOUND",
                "message": (
                    "MLB no encontró el partido."
                ),
            }

        result = extract_game_result(
            target_game
        )

        if not result:

            return {
                "success": False,
                "event_id": event_id,
                "status": "NOT_FOUND",
            }

        # -------------------------------------------------
        # Partido todavía no final
        # -------------------------------------------------

        if result["status"] != "Final":

            return {
                "success": False,
                "event_id": event_id,
                "status": result["status"],
                "detailed_status": result[
                    "detailed_status"
                ],
                "home": result["home"],
                "away": result["away"],
                "home_score": result[
                    "home_score"
                ],
                "away_score": result[
                    "away_score"
                ],
                "message": (
                    "El partido todavía no ha "
                    "terminado."
                ),
            }

        # -------------------------------------------------
        # Verificar marcador
        # -------------------------------------------------

        if (
            result["home_score"] is None
            or result["away_score"] is None
        ):

            return {
                "success": False,
                "event_id": event_id,
                "status": "Final",
                "home": result["home"],
                "away": result["away"],
                "message": (
                    "MLB marca el partido como Final, "
                    "pero todavía no existe un marcador "
                    "completo."
                ),
            }

        home_score = int(
            result["home_score"]
        )

        away_score = int(
            result["away_score"]
        )

        actual_winner = (
            result["actual_winner"]
        )

        if not actual_winner:

            return {
                "success": False,
                "event_id": event_id,
                "status": "Final",
                "home": result["home"],
                "away": result["away"],
                "home_score": home_score,
                "away_score": away_score,
                "message": (
                    "No fue posible determinar "
                    "el ganador."
                ),
            }

        # -------------------------------------------------
        # Liquidar
        # -------------------------------------------------

        settlement = settle_prediction(
            event_id=event_id,
            actual_winner=actual_winner,
            actual_home_score=home_score,
            actual_away_score=away_score,
        )

        return {
            "success": True,
            "event_id": event_id,
            "status": "Final",
            "detailed_status": result[
                "detailed_status"
            ],
            "home": result["home"],
            "away": result["away"],
            "home_score": home_score,
            "away_score": away_score,
            "actual_winner": actual_winner,
            "prediction_result": settlement.get(
                "prediction_result"
            ),
            "predicted_winner": settlement.get(
                "predicted_winner"
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


# =========================================================
# REPARAR PARTIDO PENDING
# =========================================================

@app.post("/api/v1/repair-settled/{event_id}")
def repair_settled_game(
    event_id: str
):
    """
    Busca el resultado oficial de MLB para un partido
    y liquida una predicción PENDING.

    Sirve especialmente para partidos que terminaron
    mientras la aplicación estaba abierta o sin que
    se hubiera pulsado Liquidar.
    """

    return settle_game(
        event_id=str(event_id)
    )


# =========================================================
# REPARAR TODAS LAS PREDICCIONES PENDING FINALIZADAS
# =========================================================

@app.post("/api/v1/repair-settled")
def repair_all_settled():

    try:

        supabase = get_supabase_client()

        response = (
            supabase
            .table(
                "prediction_snapshots"
            )
            .select(
                "id,event_id,model_version,"
                "result_status,created_at,"
                "features"
            )
            .eq(
                "result_status",
                "PENDING"
            )
            .order(
                "created_at",
                desc=False
            )
            .execute()
        )

        rows = (
            response.data
            or []
        )

        repaired = []
        skipped = []
        failed = []

        for row in rows:

            event_id = row.get(
                "event_id"
            )

            if not event_id:

                failed.append(
                    {
                        "prediction_id": row.get(
                            "id"
                        ),
                        "reason": (
                            "La predicción no tiene "
                            "event_id."
                        ),
                    }
                )

                continue

            try:

                result = settle_game(
                    event_id=str(
                        event_id
                    )
                )

                if result.get(
                    "success"
                ):

                    repaired.append(
                        {
                            "event_id": str(
                                event_id
                            ),
                            "prediction_result": result.get(
                                "prediction_result"
                            ),
                            "predicted_winner": result.get(
                                "predicted_winner"
                            ),
                            "actual_winner": result.get(
                                "actual_winner"
                            ),
                            "home_score": result.get(
                                "home_score"
                            ),
                            "away_score": result.get(
                                "away_score"
                            ),
                        }
                    )

                else:

                    skipped.append(
                        {
                            "event_id": str(
                                event_id
                            ),
                            "status": result.get(
                                "status"
                            ),
                            "message": result.get(
                                "message"
                            ),
                        }
                    )

            except Exception as exc:

                failed.append(
                    {
                        "event_id": str(
                            event_id
                        ),
                        "error": str(
                            exc
                        ),
                    }
                )

        return {
            "success": True,
            "total_pending": len(
                rows
            ),
            "repaired": len(
                repaired
            ),
            "skipped": len(
                skipped
            ),
            "failed": len(
                failed
            ),
            "details": {
                "repaired": repaired,
                "skipped": skipped,
                "failed": failed,
            },
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "REPAIR_SETTLED_ERROR"
                ),
                "message": (
                    "No fue posible ejecutar "
                    "la reparación automática."
                ),
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
# FRONTEND REACT
# =========================================================

if FRONTEND_ASSETS.exists():

    app.mount(
        "/assets",
        StaticFiles(
            directory=str(
                FRONTEND_ASSETS
            )
        ),
        name="frontend-assets",
    )


# =========================================================
# FRONTEND HOME
# =========================================================

@app.get(
    "/",
    include_in_schema=False
)
def frontend_home():

    if not FRONTEND_INDEX.exists():

        raise HTTPException(
            status_code=500,
            detail=(
                "Frontend no encontrado. "
                "No existe dist/index.html. "
                "Verifica que el frontend haya sido "
                "compilado correctamente durante el build."
            ),
        )

    return FileResponse(
        str(FRONTEND_INDEX)
    )
