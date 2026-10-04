import csv, io, requests
from datetime import datetime, timezone

SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
HEADERS = {"User-Agent": "Sports-Predictor-NFL/1.0.0", "Accept": "text/csv"}

def _team(v):
    v = (v or "").strip().upper()
    return {"JAC": "JAX", "LA": "LAR"}.get(v, v)

def _float(v, default=None):
    try: return float(v)
    except (TypeError, ValueError): return default

def _dt(date_v, time_v=None):
    if not date_v: return None
    s = str(date_v).replace("Z", "+00:00")
    if "T" in s:
        try: return datetime.fromisoformat(s)
        except ValueError: return None
    if time_v:
        try: return datetime.strptime(f"{date_v} {time_v}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError: pass
    try: return datetime.strptime(str(date_v), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError: return None

def _read():
    r = requests.get(SCHEDULE_URL, timeout=30, headers=HEADERS)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))

def _normalize(row):
    kickoff = _dt(row.get("gameday"), row.get("gametime"))
    return {
        "game_id": row.get("game_id"),
        "season": int(row["season"]),
        "game_type": row.get("game_type"),
        "week": row.get("week"),
        "kickoff": kickoff.isoformat() if kickoff else None,
        "gameday": row.get("gameday"),
        "gametime": row.get("gametime"),
        "away": _team(row.get("away_team")),
        "home": _team(row.get("home_team")),
        "away_score": _float(row.get("away_score")),
        "home_score": _float(row.get("home_score")),
        "stadium": row.get("stadium"),
        "roof": row.get("roof"),
        "surface": row.get("surface"),
        "temp": _float(row.get("temp")),
        "wind": _float(row.get("wind")),
        "spread_line": _float(row.get("spread_line")),
        "total_line": _float(row.get("total_line")),
        "away_qb": row.get("away_qb_name"),
        "home_qb": row.get("home_qb_name"),
    }

def load_schedule(season=2026):
    return [_normalize(r) for r in _read() if str(r.get("season")) == str(season)]

def get_game(game_id, season=2026):
    return next((g for g in load_schedule(season) if str(g["game_id"]) == str(game_id)), None)

def get_upcoming_games(season=2026, limit=20):
    now = datetime.now(timezone.utc)
    games = [g for g in load_schedule(season)
             if g["game_type"] in {"REG","WC","DIV","CON","SB"}
             and g["kickoff"] and _dt(g["kickoff"]) > now]
    return sorted(games, key=lambda x: x["kickoff"])[:limit]

def get_completed_games_before(team, cutoff, season=2026):
    team = _team(team)
    cutoff = _dt(cutoff) if isinstance(cutoff, str) else cutoff
    out = []
    for g in load_schedule(season):
        if g["game_type"] != "REG" or team not in {g["home"], g["away"]}: continue
        if g["home_score"] is None or g["away_score"] is None or not g["kickoff"]: continue
        if _dt(g["kickoff"]) >= cutoff: continue
        out.append(g)
    return sorted(out, key=lambda x: x["kickoff"], reverse=True)

def build_team_history(team, cutoff, season=2026):
    games = get_completed_games_before(team, cutoff, season)
    team = _team(team)
    wins = losses = pf = pa = 0.0
    detail = []
    for g in games:
        a, h = g["away_score"], g["home_score"]
        team_pf, team_pa = (h, a) if g["home"] == team else (a, h)
        pf += team_pf; pa += team_pa
        wins += team_pf > team_pa
        losses += team_pf <= team_pa
        detail.append({"game_id": g["game_id"], "kickoff": g["kickoff"], "point_diff": team_pf-team_pa})
    n = int(wins + losses)
    recent = detail[:5]
    return {
        "team": team, "games": n, "wins": int(wins), "losses": int(losses),
        "win_rate": round(wins/n,4) if n else .5,
        "points_for_per_game": round(pf/n,4) if n else 21.0,
        "points_against_per_game": round(pa/n,4) if n else 21.0,
        "point_diff_per_game": round((pf-pa)/n,4) if n else 0.0,
        "recent_games": len(recent),
        "recent_win_rate": round(sum(x["point_diff"]>0 for x in recent)/len(recent),4) if recent else .5,
        "recent_point_diff_per_game": round(sum(x["point_diff"] for x in recent)/len(recent),4) if recent else 0.0,
        "games_detail": detail,
    }
