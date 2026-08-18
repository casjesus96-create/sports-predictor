from datetime import date,datetime,timezone
from fastapi import FastAPI,HTTPException,Query
from pydantic import BaseModel
from .mlb_client import get_schedule
from .prediction import baseline_prediction
from .repository import save_prediction
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
