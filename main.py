from datetime import date,datetime,timezone
import requests
from fastapi import FastAPI,HTTPException,Query
from pydantic import BaseModel
from mlb_client import get_schedule
from prediction import baseline_prediction
from repository import save_prediction, save analysis
from analyzer import analyze_mlb_game
app=FastAPI(title="Sports Predictor API",version="1.0.0")
class PredictionRequest(BaseModel): event_id:str
@app.get("/health")
def health():return {"status":"ok","version":"1.0.0","utc":datetime.now(timezone.utc)}
@app.get("/api/v1/mlb/games")
def games(day:str|None=Query(None,pattern=r"^\d{4}-\d{2}-\d{2}$")):
    selected=day or date.today().isoformat()
    try:return {"date":selected,"games":get_schedule(selected)}
    except Exception as e:raise HTTPException(502,f"MLB data source unavailable: {e}")
@app.post("/api/v1/predictions/experimental")
def analyze(req:PredictionRequest):
    r=baseline_prediction()
    payload={"event_id":req.event_id,"sport":"baseball","league":"MLB","model_version":"MLB-Baseline-0.1",
    "data_cutoff":datetime.now(timezone.utc).isoformat(),"home_probability":r["home_probability"],
    "away_probability":r["away_probability"],"confidence":r["confidence"],"data_quality":r["data_quality"],
    "features":r["features"],"result_status":"PENDING"}
    return {**payload,"experimental":True,"persistence":save_prediction(payload)}
@app.post("/api/v1/analyze")
def analyze_match(payload: dict):
    sport = payload.get("sport")
    league = payload.get("league")
    game_id = payload.get("game_id")

    if not sport:
        return {
            "success": False,
            "error": "sport es obligatorio"
        }

    if not league:
        return {
            "success": False,
            "error": "league es obligatorio"
        }

    if not game_id:
        return {
            "success": False,
            "error": "game_id es obligatorio"
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
            "details": str(error)
        }

    except Exception as error:
        return {
            "success": False,
            "error": "Error interno del analizador",
            "details": str(error)
        }

    return {
        "success": False,
        "error": "Deporte o liga todavía no implementado",
        "sport": sport,
        "league": league
    }
