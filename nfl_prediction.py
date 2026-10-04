import math
MODEL_VERSION = "NFL-1.0.0"

def clamp(v, lo=.05, hi=.95): return max(lo, min(hi, v))
def _f(v, d=0.0):
    try: return float(v)
    except (TypeError, ValueError): return d
def _sigmoid(v): return 1/(1+math.exp(-max(-8,min(8,v))))

def calculate_probability(home_history, away_history, rest_home_days, rest_away_days):
    hpd=_f(home_history.get("point_diff_per_game")); apd=_f(away_history.get("point_diff_per_game"))
    hpf=_f(home_history.get("points_for_per_game"),21); apf=_f(away_history.get("points_for_per_game"),21)
    hpa=_f(home_history.get("points_against_per_game"),21); apa=_f(away_history.get("points_against_per_game"),21)
    hrpd=_f(home_history.get("recent_point_diff_per_game")); arpd=_f(away_history.get("recent_point_diff_per_game"))
    hwr=_f(home_history.get("recent_win_rate"),.5); awr=_f(away_history.get("recent_win_rate"),.5)
    rest=math.tanh((_f(rest_home_days,7)-_f(rest_away_days,7))/3)
    season_pd=math.tanh((hpd-apd)/10)
    scoring=math.tanh(((hpf-apf)-(hpa-apa))/14)
    recent_pd=math.tanh((hrpd-arpd)/10)
    signal=season_pd*.38 + scoring*.28 + recent_pd*.16 + (hwr-awr)*.10 + rest*.03 + .05
    p=clamp(_sigmoid(signal*2.2))
    return {"home":round(p,4),"away":round(1-p,4)}

def calculate_confidence(probabilities):
    d=abs(probabilities["home"]-probabilities["away"])
    return round(clamp(.50+d*.80,.50,.90),4)
