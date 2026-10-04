from datetime import datetime, timezone
from nfl_client import get_game, build_team_history
from nfl_prediction import MODEL_VERSION, calculate_probability, calculate_confidence

def _dt(v):
    return datetime.fromisoformat(str(v).replace("Z","+00:00")) if v else None

def _quality(h,a):
    n=min(h.get("games",0),a.get("games",0))
    return 100 if n>=5 else 85 if n>=3 else 70 if n>=1 else 50

def analyze_nfl_game(game_id):
    game=get_game(game_id)
    if not game:
        return {"success":False,"model_version":MODEL_VERSION,"message":"No se encontró el partido NFL.","game_id":str(game_id)}
    cutoff=_dt(game["kickoff"])
    if cutoff <= datetime.now(timezone.utc):
        return {"success":False,"model_version":MODEL_VERSION,"message":"El partido ya comenzó o terminó. NFL-1.0.0 solo usa información pre-kickoff.","game_id":str(game_id)}
    h=build_team_history(game["home"],cutoff,game["season"])
    a=build_team_history(game["away"],cutoff,game["season"])
    def rest(hist):
        if not hist["games_detail"]: return 7.0
        return max(0,(cutoff-_dt(hist["games_detail"][0]["kickoff"])).total_seconds()/86400)
    probs=calculate_probability(h,a,rest(h),rest(a))
    winner=game["home"] if probs["home"]>=probs["away"] else game["away"]
    return {
        "success":True,"model_version":MODEL_VERSION,
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "data_cutoff":cutoff.isoformat(),"game":game,
        "prediction":{"winner":winner,"home_probability":probs["home"],"away_probability":probs["away"],
                      "confidence":calculate_confidence(probs),"data_quality":_quality(h,a)},
        "factors":{"home":h,"away":a,
                   "quarterback":{"home":game.get("home_qb"),"away":game.get("away_qb"),"used_in_probability":False},
                   "weather":{"temperature":game.get("temp"),"wind":game.get("wind"),"roof":game.get("roof"),"surface":game.get("surface"),"used_in_probability":False},
                   "market":{"spread_line":game.get("spread_line"),"total_line":game.get("total_line"),"used_in_probability":False}}
    }
