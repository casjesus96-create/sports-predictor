from fastapi import FastAPI, HTTPException
import requests

from analyzer import analyze_mlb_game
from repository import (
    save_prediction,
    save_analysis,
    settle_prediction,
    get_performance,
    get_predictions,
)


app = FastAPI(
    title="Sports Predictor API",
    version="1.1.0",
)


MLB_API = "https://statsapi.mlb.com/api/v1"

MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0"
}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "sports-predictor",
        "version": "1.1.0",
    }


@app.get("/api/v1/mlb/games")
def get_mlb_games():
    try:
        url = f"{MLB_API}/schedule"

        params = {
            "sportId": 1,
            "date": "2026-09-20",
            "hydrate": "probablePitcher,team,venue",
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

        for date_block in data.get("dates", []):
            for game in date_block.get("games", []):
                game_pk = game.get("gamePk")

                teams = game.get("teams", {})

                home = teams.get("home", {})
                away = teams.get("away", {})

                games.append(
                    {
                        "game_id": game_pk,
                        "date": game.get("gameDate"),
                        "status": game.get(
                            "status",
                            {}
                        ).get(
                            "abstractGameState"
                        ),
                        "home": home.get(
                            "team",
                            {}
                        ).get("name"),
                        "away": away.get(
                            "team",
                            {}
                        ).get("name"),
                        "venue": game.get(
                            "venue",
                            {}
                        ).get("name"),
                    }
                )

        return {
            "success": True,
            "total": len(games),
            "games": games,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


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


@app.post("/api/v1/analyze")
def analyze_game(event_id: str):
    try:
        analysis = analyze_mlb_game(event_id)

        if not analysis.get("success"):
            return analysis

        persistence = save_analysis(analysis)

        analysis["persistence"] = persistence

        return analysis

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.post("/api/v1/settle/{event_id}")
def settle_game(event_id: str):
    try:
        event_id = str(event_id)

        # ---------------------------------------------------------
        # 1. Consultar primero el calendario de MLB
        # ---------------------------------------------------------

        schedule_url = f"{MLB_API}/schedule"

        schedule_params = {
            "sportId": 1,
            "gamePk": event_id,
            "hydrate": "probablePitcher,team,venue",
        }

        schedule_response = requests.get(
            schedule_url,
            params=schedule_params,
            timeout=20,
            headers=MLB_HEADERS,
        )

        # ---------------------------------------------------------
        # 2. Si MLB no encuentra el partido
        # ---------------------------------------------------------

        if schedule_response.status_code == 404:
            return {
                "success": False,
                "event_id": event_id,
                "status": "NOT_FOUND",
                "message": (
                    "MLB no encontró un partido con este "
                    "event_id. Verifica que el gamePk sea correcto."
                ),
            }

        schedule_response.raise_for_status()

        schedule_data = schedule_response.json()

        scheduled_games = []

        for date_block in schedule_data.get("dates", []):
            scheduled_games.extend(
                date_block.get("games", [])
            )

        # ---------------------------------------------------------
        # 3. Si el calendario no contiene el game_id
        # ---------------------------------------------------------

        target_game = None

        for game in scheduled_games:
            if str(game.get("gamePk")) == event_id:
                target_game = game
                break

        if target_game is None:
            return {
                "success": False,
                "event_id": event_id,
                "status": "NOT_FOUND",
                "message": (
                    "El event_id no aparece en el calendario "
                    "actual de MLB. Puede tratarse de un gamePk "
                    "incorrecto o de un partido que MLB ya no "
                    "expone mediante este endpoint."
                ),
            }

        # ---------------------------------------------------------
        # 4. Obtener información básica del partido
        # ---------------------------------------------------------

        game_status = (
            target_game
            .get("status", {})
            .get("abstractGameState")
        )

        detailed_state = (
            target_game
            .get("status", {})
            .get("detailedState")
        )

        teams = target_game.get("teams", {})

        home_team = (
            teams
            .get("home", {})
            .get("team", {})
            .get("name")
        )

        away_team = (
            teams
            .get("away", {})
            .get("team", {})
            .get("name")
        )

        home_score = (
            teams
            .get("home", {})
            .get("score")
        )

        away_score = (
            teams
            .get("away", {})
            .get("score")
        )

        # ---------------------------------------------------------
        # 5. Si todavía no terminó
        # ---------------------------------------------------------

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

        # ---------------------------------------------------------
        # 6. Si MLB no entregó marcador final
        # ---------------------------------------------------------

        if home_score is None or away_score is None:
            return {
                "success": False,
                "event_id": event_id,
                "status": "Final",
                "home": home_team,
                "away": away_team,
                "message": (
                    "MLB marca el partido como Final, pero "
                    "todavía no proporcionó el marcador completo."
                ),
            }

        home_score = int(home_score)
        away_score = int(away_score)

        # ---------------------------------------------------------
        # 7. Determinar ganador
        # ---------------------------------------------------------

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
                    "El marcador recibido no permite determinar "
                    "un ganador."
                ),
            }

        # ---------------------------------------------------------
        # 8. Actualizar la predicción en Supabase
        # ---------------------------------------------------------

        settlement = settle_prediction(
            event_id=event_id,
            actual_winner=actual_winner,
            actual_home_score=home_score,
            actual_away_score=away_score,
        )

        # ---------------------------------------------------------
        # 9. Respuesta final
        # ---------------------------------------------------------

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
            "event_id": str(event_id),
            "status": "MLB_API_ERROR",
            "message": (
                "MLB respondió con un error HTTP."
            ),
            "details": str(exc),
        }

    except requests.exceptions.RequestException as exc:
        return {
            "success": False,
            "event_id": str(event_id),
            "status": "MLB_CONNECTION_ERROR",
            "message": (
                "No fue posible comunicarse con MLB."
            ),
            "details": str(exc),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.get("/api/v1/performance")
def performance():
    try:
        return get_performance()

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Error obteniendo rendimiento del modelo",
                "details": str(exc),
            },
        )


@app.get("/api/v1/predictions")
def predictions():
    try:
        return get_predictions()

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Error obteniendo predicciones",
                "details": str(exc),
            },
        )
