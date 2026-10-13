"""Descriptive MLB run and starting-pitcher strikeout projections.

These estimates are kept separate from the official winner-probability model.
They are pregame estimates, not betting advice or guarantees.
"""
import math


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _nonnegative(value):
    result = _number(value)
    return result if result is not None and result >= 0 else None


def _rate(total, games):
    total_value = _nonnegative(total)
    games_value = _number(games)
    if total_value is None or games_value is None or games_value <= 0:
        return None
    return total_value / games_value


def parse_innings_pitched(value):
    """Parse MLB innings notation: '100.1' means 100 innings and 1 out."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if "." not in text:
            result = float(text)
        else:
            whole_text, outs_text = text.split(".", 1)
            whole = int(whole_text or "0")
            outs = int(outs_text)
            if outs not in (0, 1, 2):
                return None
            result = whole + outs / 3.0
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result < 0:
        return None
    return result


def _recent_rate(form, field):
    form = form if isinstance(form, dict) else {}
    last_15 = form.get("last_15")
    if not isinstance(last_15, dict):
        return None
    games = _number(last_15.get("games"))
    rate = _number(last_15.get(field))
    if games is None or games <= 0 or rate is None or rate < 0:
        return None
    return rate


def _team_runs_per_game(hitting_stats):
    stats = hitting_stats if isinstance(hitting_stats, dict) else {}
    return _rate(stats.get("runs"), stats.get("gamesPlayed"))


def _runs_allowed_per_game(pitching_stats):
    stats = pitching_stats if isinstance(pitching_stats, dict) else {}
    # MLB team pitching season stats expose runs allowed as "runs".
    return _rate(stats.get("runs"), stats.get("gamesPlayed"))


def _blend_run_estimate(offense_rate, opponent_allowed_rate, recent_scored, recent_allowed):
    season_inputs = [
        value for value in (offense_rate, opponent_allowed_rate)
        if value is not None
    ]
    recent_inputs = [
        value for value in (recent_scored, recent_allowed)
        if value is not None
    ]
    season_estimate = (
        sum(season_inputs) / len(season_inputs)
        if season_inputs else None
    )
    recent_estimate = (
        sum(recent_inputs) / len(recent_inputs)
        if recent_inputs else None
    )

    if season_estimate is not None and recent_estimate is not None:
        estimate = 0.70 * season_estimate + 0.30 * recent_estimate
        method = "70% season matchup + 30% recent form"
    elif season_estimate is not None:
        estimate = season_estimate
        method = "season offense/opponent run prevention"
    elif recent_estimate is not None:
        estimate = recent_estimate
        method = "recent form only; season matchup unavailable"
    else:
        return {
            "available": False,
            "expected_runs": None,
            "season_estimate": None,
            "recent_estimate": None,
            "method": "insufficient data",
            "data_points": 0,
        }

    # Defensive sanity bounds prevent malformed inputs from producing absurd outputs.
    estimate = min(20.0, max(0.0, estimate))
    return {
        "available": True,
        "expected_runs": round(estimate, 2),
        "season_estimate": round(season_estimate, 2) if season_estimate is not None else None,
        "recent_estimate": round(recent_estimate, 2) if recent_estimate is not None else None,
        "method": method,
        "data_points": len(season_inputs) + len(recent_inputs),
    }


def poisson_probability_at_least(threshold, expected_value):
    """Poisson tail P(X >= threshold), with stable recurrence for small MLB counts."""
    lam = _number(expected_value)
    if not isinstance(threshold, int) or threshold < 0 or lam is None or lam < 0:
        return None
    if threshold == 0:
        return 1.0
    if lam == 0:
        return 0.0

    probability = math.exp(-lam)
    cumulative = probability
    for k in range(1, threshold):
        probability *= lam / k
        cumulative += probability
    return min(1.0, max(0.0, 1.0 - cumulative))


def estimate_pitcher_strikeouts(pitcher_stats, opponent_hitting_stats, pitcher_name=None):
    """Estimate starter Ks from season K/9 and innings/start, if supported by data."""
    stats = pitcher_stats if isinstance(pitcher_stats, dict) else {}
    opponent = opponent_hitting_stats if isinstance(opponent_hitting_stats, dict) else {}

    strikeouts = _nonnegative(stats.get("strikeOuts", stats.get("strikeouts")))
    innings = parse_innings_pitched(stats.get("inningsPitched"))
    starts = _nonnegative(stats.get("gamesStarted"))
    appearances = _nonnegative(stats.get("gamesPlayed"))

    if strikeouts is None or innings is None or innings <= 0:
        return {
            "available": False,
            "pitcher_name": pitcher_name,
            "expected_strikeouts": None,
            "probability_5_plus": None,
            "probability_6_plus": None,
            "probability_7_plus": None,
            "strikeouts_per_9": None,
            "expected_innings": None,
            "opponent_strikeout_rate": None,
            "method": "pitcher strikeouts or innings pitched unavailable",
        }

    strikeouts_per_9 = strikeouts / innings * 9.0
    if starts is not None and starts > 0:
        expected_innings = innings / starts
        innings_basis = "season innings / games started"
    elif appearances is not None and appearances > 0:
        expected_innings = innings / appearances
        innings_basis = "season innings / appearances; starter role uncertain"
    else:
        expected_innings = None
        innings_basis = "unavailable"

    if expected_innings is None or expected_innings <= 0:
        return {
            "available": False,
            "pitcher_name": pitcher_name,
            "expected_strikeouts": None,
            "probability_5_plus": None,
            "probability_6_plus": None,
            "probability_7_plus": None,
            "strikeouts_per_9": round(strikeouts_per_9, 3),
            "expected_innings": None,
            "opponent_strikeout_rate": None,
            "method": "innings per start unavailable",
        }

    # A reliever-heavy season sample should not imply a full starter workload.
    expected_innings = min(7.5, max(2.0, expected_innings))
    expected_ks = max(0.0, strikeouts_per_9 * expected_innings / 9.0)

    opponent_so = _nonnegative(opponent.get("strikeOuts", opponent.get("strikeouts")))
    opponent_ab = _nonnegative(opponent.get("atBats"))
    opponent_k_rate = (
        opponent_so / opponent_ab
        if opponent_so is not None and opponent_ab is not None and opponent_ab > 0
        else None
    )

    return {
        "available": True,
        "pitcher_name": pitcher_name,
        "expected_strikeouts": round(expected_ks, 2),
        "probability_5_plus": round(poisson_probability_at_least(5, expected_ks), 4),
        "probability_6_plus": round(poisson_probability_at_least(6, expected_ks), 4),
        "probability_7_plus": round(poisson_probability_at_least(7, expected_ks), 4),
        "strikeouts_per_9": round(strikeouts_per_9, 3),
        "expected_innings": round(expected_innings, 2),
        "innings_basis": innings_basis,
        "opponent_strikeout_rate": round(opponent_k_rate, 4) if opponent_k_rate is not None else None,
        "opponent_strikeout_rate_note": (
            "Context only; not used to adjust the probability until a validated league baseline is available."
        ),
        "method": "season K/9 × estimated innings; Poisson approximation",
    }


def calculate_game_projections(
    home_hitting,
    away_hitting,
    home_pitching,
    away_pitching,
    home_form,
    away_form,
    home_pitcher_stats,
    away_pitcher_stats,
    home_pitcher_name=None,
    away_pitcher_name=None,
):
    """Return run and starter-K projections without changing win probabilities."""
    home_season_runs = _team_runs_per_game(home_hitting)
    away_season_runs = _team_runs_per_game(away_hitting)
    home_allowed = _runs_allowed_per_game(home_pitching)
    away_allowed = _runs_allowed_per_game(away_pitching)

    home_recent_scored = _recent_rate(home_form, "runs_scored_per_game")
    home_recent_allowed = _recent_rate(home_form, "runs_allowed_per_game")
    away_recent_scored = _recent_rate(away_form, "runs_scored_per_game")
    away_recent_allowed = _recent_rate(away_form, "runs_allowed_per_game")

    home_runs = _blend_run_estimate(
        home_season_runs, away_allowed, home_recent_scored, away_recent_allowed
    )
    away_runs = _blend_run_estimate(
        away_season_runs, home_allowed, away_recent_scored, home_recent_allowed
    )

    total_runs = (
        round(home_runs["expected_runs"] + away_runs["expected_runs"], 2)
        if home_runs["available"] and away_runs["available"] else None
    )

    home_ks = estimate_pitcher_strikeouts(
        home_pitcher_stats, away_hitting, home_pitcher_name
    )
    away_ks = estimate_pitcher_strikeouts(
        away_pitcher_stats, home_hitting, away_pitcher_name
    )

    return {
        "run_projection": {
            "available": home_runs["available"] and away_runs["available"],
            "home": home_runs,
            "away": away_runs,
            "total_expected_runs": total_runs,
            "projected_score": (
                f'{int(round(away_runs["expected_runs"]))}-'
                f'{int(round(home_runs["expected_runs"]))}'
                if home_runs["available"] and away_runs["available"] else None
            ),
            "note": (
                "Descriptive estimate from season run rates and recent last-15 form; "
                "not part of the official win-probability model."
            ),
        },
        "pitcher_strikeout_projection": {
            "available": home_ks["available"] or away_ks["available"],
            "home_pitcher": home_ks,
            "away_pitcher": away_ks,
            "note": (
                "Starter strikeouts are estimated from season K/9 and innings per start. "
                "Threshold probabilities use a Poisson approximation and require validation."
            ),
        },
    }
