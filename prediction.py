import math
from datetime import datetime, timezone

from form_engine import get_matchup_form
from matchup_engine import get_matchup_data


MODEL_VERSION = "2.0.0-matchup"

WEIGHTS = {
    "general_form": 0.20,
    "batting_split": 0.18,
    "offensive_volume": 0.10,
    "h2h": 0.10,
    "run_differential": 0.12,
    "pitcher": 0.20,
    "home_advantage": 0.10,
}


def clamp(value, minimum=0.05, maximum=0.95):
    return max(minimum, min(maximum, value))


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def sigmoid(value):
    try:
        return 1.0 / (1.0 + math.exp(-value))
    except OverflowError:
        return 0.0 if value < 0 else 1.0


def calculate_recent_form(form):
    last_5 = form.get("last_5", {})
    last_10 = form.get("last_10", {})
    last_15 = form.get("last_15", {})

    return (
        safe_float(last_5.get("win_rate"), 0.50) * 0.50
        + safe_float(last_10.get("win_rate"), 0.50) * 0.30
        + safe_float(last_15.get("win_rate"), 0.50) * 0.20
    )


def calculate_run_differential(form):
    values = []

    for key in ("last_5", "last_10", "last_15"):
        data = form.get(key, {})
        games = safe_float(data.get("games"), 0)
        differential = safe_float(data.get("run_differential"), 0)
        values.append(differential / games if games > 0 else 0.0)

    return values[0] * 0.50 + values[1] * 0.30 + values[2] * 0.20


def calculate_h2h_signal(h2h):
    if not h2h.get("available"):
        return 0.0

    games = safe_int(h2h.get("games"), 0)
    if games <= 0:
        return 0.0

    home_wins = safe_int(h2h.get("home_team_wins"), 0)
    away_wins = safe_int(h2h.get("away_team_wins"), 0)

    return max(-1.0, min(1.0, (home_wins - away_wins) / games))


def calculate_split_signal(home_split, away_split):
    home_available = home_split.get("available", False)
    away_available = away_split.get("available", False)

    if not home_available and not away_available:
        return 0.0

    def offensive_score(split):
        if not split.get("available"):
            return 0.0

        ops = safe_float(split.get("ops"), 0.700)
        avg = safe_float(split.get("avg"), 0.250)
        obp = safe_float(split.get("obp"), 0.320)
        slg = safe_float(split.get("slg"), 0.400)

        return (
            ((ops - 0.700) / 0.200) * 0.55
            + ((avg - 0.250) / 0.050) * 0.15
            + ((obp - 0.320) / 0.050) * 0.15
            + ((slg - 0.400) / 0.100) * 0.15
        )

    return math.tanh((offensive_score(home_split) - offensive_score(away_split)) / 2.0)


def calculate_offensive_volume_signal(home_split, away_split):
    def score(split):
        if not split.get("available"):
            return 0.0

        games = max(safe_float(split.get("games"), 0.0), 1.0)
        hits_pg = safe_float(split.get("hits"), 0.0) / games
        hr_pg = safe_float(split.get("home_runs"), 0.0) / games
        runs_pg = safe_float(split.get("runs"), 0.0) / games
        walks_pg = safe_float(split.get("walks"), 0.0) / games
        strikeouts_pg = safe_float(split.get("strikeouts"), 0.0) / games

        return (
            ((hits_pg - 8.0) / 2.0) * 0.30
            + ((hr_pg - 1.0) / 0.60) * 0.25
            + ((runs_pg - 4.5) / 1.5) * 0.20
            + ((walks_pg - 3.2) / 1.0) * 0.10
            - ((strikeouts_pg - 8.5) / 2.0) * 0.15
        )

    return math.tanh((score(home_split) - score(away_split)) / 2.0)


def calculate_general_context_signal(home_context, away_context):
    home_win_rate = safe_float(home_context.get("win_rate"), 0.500)
    away_win_rate = safe_float(away_context.get("win_rate"), 0.500)

    home_games = max(safe_int(home_context.get("games"), 1), 1)
    away_games = max(safe_int(away_context.get("games"), 1), 1)

    home_run_per_game = safe_float(home_context.get("run_differential"), 0) / home_games
    away_run_per_game = safe_float(away_context.get("run_differential"), 0) / away_games

    win_signal = math.tanh((home_win_rate - away_win_rate) * 4.0)
    run_signal = math.tanh((home_run_per_game - away_run_per_game) / 2.0)

    return win_signal * 0.60 + run_signal * 0.40


def calculate_pitcher_signal(home_pitcher, away_pitcher):
    home_available = home_pitcher.get("available", False)
    away_available = away_pitcher.get("available", False)

    if home_available and away_available:
        return 0.0
    if home_available and not away_available:
        return 0.15
    if away_available and not home_available:
        return -0.15
    return 0.0


def calculate_data_quality(matchup, matchup_form):
    score = 0

    pitchers = matchup.get("pitchers", {})
    if pitchers.get("home", {}).get("available"):
        score += 15
    if pitchers.get("away", {}).get("available"):
        score += 15

    h2h = matchup.get("h2h", {})
    if h2h.get("available"):
        games = safe_int(h2h.get("games"), 0)
        score += 15 if games >= 10 else 10 if games >= 5 else 5 if games > 0 else 0

    splits = matchup.get("batting_splits", {})
    if splits.get("home_team", {}).get("batting_split", {}).get("available"):
        score += 15
    if splits.get("away_team", {}).get("batting_split", {}).get("available"):
        score += 15

    context = matchup.get("general_context", {})
    if context.get("home", {}).get("available"):
        score += 5
    if context.get("away", {}).get("available"):
        score += 5

    home_last_15 = matchup_form.get("home", {}).get("last_15", {})
    away_last_15 = matchup_form.get("away", {}).get("last_15", {})
    if safe_int(home_last_15.get("games"), 0) >= 15:
        score += 2
    if safe_int(away_last_15.get("games"), 0) >= 15:
        score += 2

    return min(score, 100)


def calculate_probability(matchup, matchup_form):
    context = matchup.get("general_context", {})
    home_context = context.get("home", {})
    away_context = context.get("away", {})

    splits = matchup.get("batting_splits", {})
    home_split = splits.get("home_team", {}).get("batting_split", {})
    away_split = splits.get("away_team", {}).get("batting_split", {})

    pitchers = matchup.get("pitchers", {})
    home_pitcher = pitchers.get("home", {})
    away_pitcher = pitchers.get("away", {})

    h2h = matchup.get("h2h", {})

    home_form = matchup_form.get("home", {})
    away_form = matchup_form.get("away", {})

    general_signal = calculate_general_context_signal(home_context, away_context)
    split_signal = calculate_split_signal(home_split, away_split)
    offensive_volume_signal = calculate_offensive_volume_signal(home_split, away_split)
    h2h_signal = calculate_h2h_signal(h2h)
    pitcher_signal = calculate_pitcher_signal(home_pitcher, away_pitcher)

    home_run_form = calculate_run_differential(home_form)
    away_run_form = calculate_run_differential(away_form)
    run_signal = math.tanh((home_run_form - away_run_form) / 2.0)

    home_advantage_signal = 1.0

    combined_signal = (
        general_signal * WEIGHTS["general_form"]
        + split_signal * WEIGHTS["batting_split"]
        + offensive_volume_signal * WEIGHTS["offensive_volume"]
        + h2h_signal * WEIGHTS["h2h"]
        + run_signal * WEIGHTS["run_differential"]
        + pitcher_signal * WEIGHTS["pitcher"]
        + home_advantage_signal * WEIGHTS["home_advantage"]
    )

    probability_home = clamp(sigmoid(combined_signal * 2.0))
    probability_away = 1.0 - probability_home

    return {
        "home_probability": round(probability_home, 4),
        "away_probability": round(probability_away, 4),
        "signals": {
            "general_context": round(general_signal, 4),
            "batting_split": round(split_signal, 4),
            "offensive_volume": round(offensive_volume_signal, 4),
            "h2h": round(h2h_signal, 4),
            "run_differential": round(run_signal, 4),
            "pitcher": round(pitcher_signal, 4),
            "home_advantage": round(home_advantage_signal, 4),
        },
    }


def analyze_game(
    game_id,
    home_team_id,
    away_team_id,
    before_date=None,
    season=None,
    game_type="R",
):
    """Ejecuta el único modelo oficial pregame 2.0.0-matchup."""
    matchup = get_matchup_data(
        game_id=game_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        before_date=before_date,
        season=season,
        game_type=game_type,
    )

    matchup_form = get_matchup_form(
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        before_date=before_date,
    )

    probabilities = calculate_probability(matchup, matchup_form)

    home_probability = probabilities["home_probability"]
    away_probability = probabilities["away_probability"]
    separation = abs(home_probability - away_probability)

    return {
        "success": True,
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_cutoff": before_date,
        "game": {
            "game_id": str(game_id),
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "before_date": before_date,
            "season": matchup.get("season"),
        },
        "prediction": {
            "projected_side": "home" if home_probability >= away_probability else "away",
            "home_probability": home_probability,
            "away_probability": away_probability,
            "confidence": round(0.50 + separation * 0.50, 4),
            "data_quality": calculate_data_quality(matchup, matchup_form),
        },
        "signals": probabilities["signals"],
        "matchup": matchup,
        "recent_form": matchup_form,
    }
