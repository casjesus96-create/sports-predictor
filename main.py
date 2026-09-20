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
            headers={
                "User-Agent": "Sports-Predictor/1.0"
            },
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
        url = f"{MLB_API}/game/{event_id}/feed/live"

        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Sports-Predictor/1.0"
            },
        )

        response.raise_for_status()

        data = response.json()

        game_data = data.get("gameData", {})
        live_data = data.get("liveData", {})

        status = (
            game_data
            .get("status", {})
            .get("abstractGameState")
        )

        teams = game_data.get("teams", {})

        home_team = (
            teams
            .get("home", {})
            .get("name")
        )

        away_team = (
            teams
            .get("away", {})
            .get("name")
        )

        if status != "Final":
            return {
                "success": False,
                "event_id": str(event_id),
                "status": status,
                "message": (
                    "El partido todavía no ha terminado. "
                    "La predicción permanece PENDING."
                ),
            }

        linescore = live_data.get(
            "linescore",
            {}
        )

        teams_score = linescore.get(
            "teams",
            {}
        )

        home_score = (
            teams_score
            .get("home", {})
            .get("runs")
        )

        away_score = (
            teams_score
            .get("away", {})
            .get("runs")
        )

        if home_score is None or away_score is None:
            return {
                "success": False,
                "event_id": str(event_id),
                "status": status,
                "message": (
                    "El partido figura como Final, "
                    "pero MLB todavía no proporcionó "
                    "el marcador completo."
                ),
            }

        home_score = int(home_score)
        away_score = int(away_score)

        if home_score > away_score:
            actual_winner = home_team
        elif away_score > home_score:
            actual_winner = away_team
        else:
            return {
                "success": False,
                "event_id": str(event_id),
                "status": status,
                "message": (
                    "El marcador recibido no permite "
                    "determinar un ganador."
                ),
            }

        settlement = settle_prediction(
            event_id=event_id,
            actual_winner=actual_winner,
            actual_home_score=home_score,
            actual_away_score=away_score,
        )

        return {
            "success": True,
            "event_id": str(event_id),
            "status": status,
            "home": home_team,
            "away": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "actual_winner": actual_winner,
            "settled_at": settlement.get(
                "settled_at"
            ),
            "settlement": settlement,
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
