import requests
BASE_URL="https://statsapi.mlb.com/api/v1"
def get_schedule(day):
    r=requests.get(f"{BASE_URL}/schedule",params={"sportId":1,"date":day,"hydrate":"team,probablePitcher,linescore"},timeout=15)
    r.raise_for_status(); out=[]
    for block in r.json().get("dates",[]):
        for g in block.get("games",[]):
            h,a=g["teams"]["home"],g["teams"]["away"]
            out.append({"game_id":str(g["gamePk"]),"date":g.get("gameDate"),
            "status":g.get("status",{}).get("abstractGameState"),
            "detailed_status":g.get("status",{}).get("detailedState"),
            "home":{"id":h["team"].get("id"),"name":h["team"].get("name"),"probable_pitcher":(h.get("probablePitcher") or {}).get("fullName")},
            "away":{"id":a["team"].get("id"),"name":a["team"].get("name"),"probable_pitcher":(a.get("probablePitcher") or {}).get("fullName")},
            "venue":(g.get("venue") or {}).get("name")})
    return out
