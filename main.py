from datetime import date, datetime, timezone

import requests
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from mlb_client import get_schedule
from prediction import baseline_prediction
from repository import (
    save_prediction,
    save_analysis,
    settle_prediction,
    get_performance,
)
from analyzer import analyze_mlb_game


app = FastAPI(
    title="Sports Predictor API",
    version="1.0.0",
)


class PredictionRequest(BaseModel):
    event_id: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "utc": datetime.now(timezone.utc),
    }


@app.get("/api/v1/mlb/games")
def games(
    day: str | None = Query(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
):
    selected = day or date.today().isoformat()

    try:
        return {
            "date": selected,
            "games": get_schedule(selected),
        }
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"MLB data source unavailable: {error}",
        )


@app.post("/api/v1/predictions/experimental")
def analyze(req: PredictionRequest):
    r = baseline_prediction()

    payload = {
        "event_id": req.event_id,
        "sport": "baseball",
        "league": "MLB",
        "model_version": "MLB-Baseline-0.1",
        "data_cutoff": datetime.now(
            timezone.utc
        ).isoformat(),
        "home_probability": r["home_probability"],
        "away_probability": r["away_probability"],
        "confidence": r["confidence"],
        "data_quality": r["data_quality"],
        "features": r["features"],
        "result_status": "PENDING",
    }

    return {
        **payload,
        "experimental": True,
        "persistence": save_prediction(payload),
    }


@app.post("/api/v1/analyze")
def analyze_match(payload: dict):
    sport = payload.get("sport")
    league = payload.get("league")
    game_id = payload.get("game_id")

    if not sport:
        return {
            "success": False,
            "error": "sport es obligatorio",
        }

    if not league:
        return {
            "success": False,
            "error": "league es obligatorio",
        }

    if not game_id:
        return {
            "success": False,
            "error": "game_id es obligatorio",
        }

    sport = sport.lower()
    league = league.lower()

    if sport == "baseball" and league == "mlb":
        try:
            analysis = analyze_mlb_game(game_id)

            if not analysis.get("success"):
                return analysis

            persistence = save_analysis(analysis)
            analysis["persistence"] = persistence

            return analysis

        except requests.RequestException as error:
            return {
                "success": False,
                "error": "Error obteniendo datos de MLB",
                "details": str(error),
            }

        except Exception as error:
            return {
                "success": False,
                "error": "Error interno del analizador",
                "details": str(error),
            }

    return {
        "success": False,
        "error": "Deporte o liga todavía no implementado",
        "sport": sport,
        "league": league,
    }


@app.post("/api/v1/settle/{event_id}")
def settle_event(event_id: str):
    try:
        url = (
            f"https://statsapi.mlb.com/api/v1.1/"
            f"game/{event_id}/feed/live"
        )

        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Sports-Predictor/1.0",
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

        if status != "Final":
            return {
                "success": False,
                "event_id": event_id,
                "status": status,
                "message": (
                    "El partido todavía no ha terminado. "
                    "La predicción permanece PENDING."
                ),
            }

        teams = game_data.get("teams", {})
        home_team = teams.get("home", {})
        away_team = teams.get("away", {})

        home_name = home_team.get("name")
        away_name = away_team.get("name")

        linescore = live_data.get("linescore", {})
        linescore_teams = linescore.get("teams", {})

        home_score = (
            linescore_teams
            .get("home", {})
            .get("runs")
        )

        away_score = (
            linescore_teams
            .get("away", {})
            .get("runs")
        )

        if home_score is None or away_score is None:
            return {
                "success": False,
                "event_id": event_id,
                "message": (
                    "El partido figura como Final, "
                    "pero no se pudo obtener el marcador."
                ),
            }

        if home_score > away_score:
            actual_winner = home_name
        elif away_score > home_score:
            actual_winner = away_name
        else:
            return {
                "success": False,
                "event_id": event_id,
                "message": (
                    "El partido terminó empatado. "
                    "No se liquidará como ganador/perdedor."
                ),
            }

        settlement = settle_prediction(
            event_id,
            actual_winner,
        )

        return {
            "success": True,
            "event_id": event_id,
            "status": "FINAL",
            "home": home_name,
            "away": away_name,
            "home_score": home_score,
            "away_score": away_score,
            "actual_winner": actual_winner,
            "settled_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "settlement": settlement,
        }

    except requests.RequestException as error:
        return {
            "success": False,
            "error": "Error obteniendo resultado de MLB",
            "details": str(error),
        }

    except Exception as error:
        return {
            "success": False,
            "error": "Error interno al liquidar el partido",
            "details": str(error),
        }


@app.get("/api/v1/performance")
def performance():
    try:
        return get_performance()

    except Exception as error:
        return {
            "success": False,
            "error": "Error obteniendo rendimiento del modelo",
            "details": str(error),
        }
