from datetime import datetime, timezone
from repository import get_supabase_client

MODEL_VERSION="NFL-1.0.0"

def save_nfl_analysis(analysis):
    if not analysis.get("success"): return {"success":False,"saved":False,"message":"No se puede guardar un análisis fallido."}
    game=analysis["game"]; pred=analysis["prediction"]; factors=analysis.get("factors") or {}
    event_id=game.get("game_id")
    if not event_id: raise ValueError("El análisis NFL no contiene game_id.")
    sb=get_supabase_client()
    version=analysis.get("model_version",MODEL_VERSION)
    payload={
        "event_id":str(event_id),"sport":"football","league":"NFL","model_version":version,
        "created_at":analysis.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "data_cutoff":analysis.get("data_cutoff"),
        "home_probability":pred.get("home_probability"),"away_probability":pred.get("away_probability"),
        "confidence":pred.get("confidence"),"data_quality":pred.get("data_quality",0),
        "features":{"game":game,"factors":factors,"predicted_winner":pred.get("winner")},
        "result_status":"PENDING","actual_winner":None,"actual_home_score":None,
        "actual_away_score":None,"settled_at":None,"prediction_result":None
    }
    existing=(sb.table("prediction_snapshots").select("id")
              .eq("event_id",str(event_id)).eq("model_version",version)
              .eq("result_status","PENDING").order("created_at",desc=True).limit(1).execute())
    if existing.data:
        r=sb.table("prediction_snapshots").update(payload).eq("id",existing.data[0]["id"]).execute()
        return {"success":True,"saved":True,"updated":True,"data":r.data}
    r=sb.table("prediction_snapshots").insert(payload).execute()
    return {"success":True,"saved":True,"updated":False,"data":r.data}
