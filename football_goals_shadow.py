"""Advanced pre-match football goals candidate. Shadow-only; never official."""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Any

MODEL_VERSION = "FOOTBALL-GOALS-SHADOW-0.1.0"
HALF_LIFE_DAYS = 120.0
PRIOR_MATCHES = 6.0
H2H_PRIOR = 10.0
H2H_MAX_WEIGHT = 0.18
MAX_GOALS = 10


def _dt(value: Any):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (TypeError, ValueError):
        return None


def _poisson(rate: float, goals: int) -> float:
    return math.exp(-rate) * rate**goals / math.factorial(goals)


def _rate(values, prior):
    total_weight = sum(weight for _value, weight in values)
    return (sum(value*weight for value,weight in values)+prior*PRIOR_MATCHES)/(total_weight+PRIOR_MATCHES)


def predict_advanced_shadow(home_team: str, away_team: str, matches: list[dict[str,Any]], kickoff_at: str):
    """Weighted form + home/away split + opponent defence + shrunk H2H."""
    if not home_team.strip() or not away_team.strip() or home_team.casefold()==away_team.casefold():
        raise ValueError("Se requieren dos equipos distintos.")
    cutoff=_dt(kickoff_at)
    if cutoff is None:
        raise ValueError("kickoff_at debe incluir zona horaria.")
    rows=[]; excluded=0
    for item in matches:
        if str(item.get("status","")).upper() not in {"FINISHED","AWARDED"}:
            continue
        h=str((item.get("homeTeam") or {}).get("name") or "").strip()
        a=str((item.get("awayTeam") or {}).get("name") or "").strip()
        sc=(item.get("score") or {}).get("fullTime") or {}
        hg,ag=sc.get("home"),sc.get("away")
        dt=_dt(item.get("utcDate") or item.get("date"))
        if not h or not a or h.casefold()==a.casefold() or dt is None:
            continue
        if not isinstance(hg,int) or isinstance(hg,bool) or hg<0 or not isinstance(ag,int) or isinstance(ag,bool) or ag<0:
            continue
        if dt>=cutoff:
            excluded+=1; continue
        age=max(0.0,(cutoff-dt).total_seconds()/86400)
        weight=math.exp(-math.log(2)*age/HALF_LIFE_DAYS)
        rows.append((h,a,hg,ag,dt,weight))
    if not rows:
        return {"available":False,"reason":"No hay resultados fechados anteriores al kickoff.","model_version":MODEL_VERSION}
    weight_sum=sum(r[5] for r in rows)
    league_home=max(.15,sum(r[2]*r[5] for r in rows)/weight_sum)
    league_away=max(.15,sum(r[3]*r[5] for r in rows)/weight_sum)
    records={}; conceded={}
    for h,a,hg,ag,dt,w in rows:
        records.setdefault(h.casefold(),[]).append(("home",float(hg),float(ag),a,dt,w))
        records.setdefault(a.casefold(),[]).append(("away",float(ag),float(hg),h,dt,w))
        conceded.setdefault(h.casefold(),[]).append((float(ag),w))
        conceded.setdefault(a.casefold(),[]).append((float(hg),w))

    def form(team, venue, league_for, league_against):
        all_rows=sorted(records.get(team.casefold(),[]),key=lambda r:r[4],reverse=True)
        venue_rows=[r for r in all_rows if r[0]==venue][:8]
        recent=all_rows[:10]
        if len(all_rows)<5 or len(venue_rows)<3:
            return None
        attack=.70*_rate([(r[1],r[5]) for r in venue_rows],league_for)+.30*_rate([(r[1],r[5]) for r in recent],league_for)
        defence=.70*_rate([(r[2],r[5]) for r in venue_rows],league_against)+.30*_rate([(r[2],r[5]) for r in recent],league_against)
        # Adjust recent attack for opponents' weighted goals-conceded rate.
        adjusted=[]
        for r in recent:
            opp_rows=conceded.get(r[3].casefold(),[])
            denom=sum(w for _g,w in opp_rows)
            opp_conceded=sum(g*w for g,w in opp_rows)/denom if denom else league_for
            factor=max(.80,min(1.20,league_for/max(.25,opp_conceded)))
            adjusted.append((r[1]*factor,r[5]))
        adjusted_attack=sum(g*w for g,w in adjusted)/sum(w for _g,w in adjusted)
        attack=.75*attack+.25*adjusted_attack
        return {"attack":attack,"defence":defence,"matches":len(all_rows),"venue_matches":len(venue_rows)}
    hf=form(home_team,"home",league_home,league_away)
    af=form(away_team,"away",league_away,league_home)
    if not hf or not af:
        return {"available":False,"reason":"Muestra insuficiente: mínimo 5 partidos totales y 3 en condición local/visitante por equipo.",
                "model_version":MODEL_VERSION,"sample":{"home_matches":len(records.get(home_team.casefold(),[])),"away_matches":len(records.get(away_team.casefold(),[]))}}
    lam_h=max(.15,min(4.5,hf["attack"]*af["defence"]/league_home))
    lam_a=max(.15,min(4.5,af["attack"]*hf["defence"]/league_away))
    h2h=[]
    for h,a,hg,ag,dt,w in rows:
        if {h.casefold(),a.casefold()}=={home_team.casefold(),away_team.casefold()}:
            h2h.append((float(hg),float(ag),dt) if h.casefold()==home_team.casefold() else (float(ag),float(hg),dt))
    h2h=sorted(h2h,key=lambda r:r[2],reverse=True)[:6]
    n=len(h2h); hweight=min(H2H_MAX_WEIGHT,H2H_MAX_WEIGHT*n/(n+H2H_PRIOR))
    if n:
        lam_h=(1-hweight)*lam_h+hweight*sum(r[0] for r in h2h)/n
        lam_a=(1-hweight)*lam_a+hweight*sum(r[1] for r in h2h)/n
    hp=[_poisson(lam_h,g) for g in range(11)]; ap=[_poisson(lam_a,g) for g in range(11)]
    matrix=[[hp[h]*ap[a] for a in range(11)] for h in range(11)]
    z=sum(sum(row) for row in matrix); matrix=[[p/z for p in row] for row in matrix]
    ph=sum(matrix[h][a] for h in range(11) for a in range(11) if h>a)
    pd=sum(matrix[g][g] for g in range(11))
    pa=sum(matrix[h][a] for h in range(11) for a in range(11) if h<a)
    btts=sum(matrix[h][a] for h in range(1,11) for a in range(1,11))
    totals={}
    for line in (1.5,2.5,3.5):
        over=sum(matrix[h][a] for h in range(11) for a in range(11) if h+a>line)
        key=str(line).replace(".","_")
        totals["over_"+key]=round(over,6); totals["under_"+key]=round(1-over,6)
    scores=sorted(((matrix[h][a],h,a) for h in range(11) for a in range(11)),reverse=True)[:5]
    return {
      "available":True,"model_version":MODEL_VERSION,"status":"SHADOW_ONLY_NOT_CALIBRATED",
      "probabilities":{"home":round(ph,6),"draw":round(pd,6),"away":round(pa,6)},
      "expected_goals":{"home":round(lam_h,3),"away":round(lam_a,3),"total":round(lam_h+lam_a,3)},
      "goal_markets":{"both_teams_to_score":{"yes":round(btts,6),"no":round(1-btts,6)},"total_goals":totals},
      "most_likely_scorelines":[{"home":h,"away":a,"probability":round(p,6)} for p,h,a in scores],
      "form":{"home":{"weighted_goals_for":round(hf["attack"],3),"weighted_goals_against":round(hf["defence"],3),"matches":hf["matches"],"home_matches":hf["venue_matches"]},
              "away":{"weighted_goals_for":round(af["attack"],3),"weighted_goals_against":round(af["defence"],3),"matches":af["matches"],"away_matches":af["venue_matches"]}},
      "h2h":{"sample_size":n,"average_home_team_goals":round(sum(r[0] for r in h2h)/n,3) if n else None,
             "average_away_team_goals":round(sum(r[1] for r in h2h)/n,3) if n else None,
             "both_teams_scored_rate":round(sum(1 for h,a,_d in h2h if h>0 and a>0)/n,3) if n else None,
             "weight_applied":round(hweight,4)},
      "sample":{"league_matches":len(rows),"home_team_matches":hf["matches"],"away_team_matches":af["matches"],"excluded_at_or_after_kickoff":excluded},
      "calibration":{"status":"not_calibrated","note":"No se afirma 90% de acierto; requiere validación walk-forward por liga."},
      "recommendation":{"status":"NO_PLAY_UNTIL_VALIDATED","reason":"Candidato sombra sin calibración demostrada."}
    }
