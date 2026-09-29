import math

MODEL_VERSION = "2.0.0-matchup"


def clamp(value, minimum=0.05, maximum=0.95):
    return max(minimum, min(maximum, value))


def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_recent_form_score(form):
    last_5 = form.get("last_5", {})
    last_10 = form.get("last_10", {})
    last_15 = form.get("last_15", {})
    return (
        safe_float(last_5.get("win_rate"), 0.5) * 0.50
        + safe_float(last_10.get("win_rate"), 0.5) * 0.30
        + safe_float(last_15.get("win_rate"), 0.5) * 0.20
    )


def calculate_run_form_score(form):
    values = []
    for key in ("last_5", "last_10", "last_15"):
        block = form.get(key, {})
        games = safe_float(block.get("games"), 0)
        diff = safe_float(block.get("run_differential"), 0)
        values.append(diff / games if games > 0 else 0)
    return values[0] * 0.50 + values[1] * 0.30 + values[2] * 0.20


def calculate_probability(
    home_hitting,
    away_hitting,
    home_pitching,
    away_pitching,
    home_pitcher,
    away_pitcher,
    home_form,
    away_form,
):
    """
    Modelo oficial MLB 2.0.0-matchup.

    Los pesos se mantienen exactamente como estaban.
    H2H, splits y bullpen se recopilan, pero todavía no
    reciben peso predictivo.
    """
    home_score = 0.50

    home_ops = safe_float(home_hitting.get("ops"), 0.700)
    away_ops = safe_float(away_hitting.get("ops"), 0.700)
    home_score += (home_ops - away_ops) * 0.35

    home_era = safe_float(home_pitching.get("era"), 4.50)
    away_era = safe_float(away_pitching.get("era"), 4.50)
    home_score += (away_era - home_era) * 0.035

    home_sp_era = safe_float(home_pitcher.get("era"))
    away_sp_era = safe_float(away_pitcher.get("era"))
    if home_sp_era is not None and away_sp_era is not None:
        home_score += (away_sp_era - home_sp_era) * 0.025

    home_score += 0.025

    form_difference = (
        calculate_recent_form_score(home_form)
        - calculate_recent_form_score(away_form)
    )
    home_score += form_difference * 0.12

    run_difference = (
        calculate_run_form_score(home_form)
        - calculate_run_form_score(away_form)
    )
    home_score += math.tanh(run_difference / 3.0) * 0.04

    probability = clamp(home_score)
    return {
        "home": round(probability, 4),
        "away": round(1 - probability, 4),
    }
