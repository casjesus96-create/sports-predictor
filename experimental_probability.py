"""Research-only MLB probability adjustment, separate from the official model.

The weights below are provisional heuristic weights, not fitted parameters.
This layer never changes MODEL_VERSION or the official probability.
All source inputs must be pregame and are supplied by the existing engines.
"""
import math

EXPERIMENTAL_VERSION = "mlb-context-experimental-0.1"
MIN_PROBABILITY = 0.05
MAX_PROBABILITY = 0.95


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _clamp(value, minimum=-1.0, maximum=1.0):
    return max(minimum, min(maximum, value))


def _bounded_signal(value, scale):
    number = _number(value)
    if number is None or scale <= 0:
        return None
    return math.tanh(number / scale)


def _bvp_lineup_signal(team):
    """Return a reliability-shrunk OPS signal only for a confirmed lineup."""
    if not isinstance(team, dict) or not team.get("lineup_confirmed"):
        return None, 0.0, 0
    hitters = team.get("hitters") or []
    weighted_ops = 0.0
    total_weight = 0.0
    total_pa = 0
    for hitter in hitters:
        stats = (hitter or {}).get("vs_pitcher") or {}
        if not stats.get("available"):
            continue
        ops = _number(stats.get("ops"))
        sample = _number(stats.get("plate_appearances"))
        if sample is None or sample <= 0:
            sample = _number(stats.get("at_bats"))
        if ops is None or sample is None or sample <= 0:
            continue
        # Prevent one batter with a tiny sample from dominating the lineup.
        weight = min(sample, 30.0)
        weighted_ops += ops * weight
        total_weight += weight
        total_pa += int(sample)
    if total_weight <= 0:
        return None, 0.0, 0
    reliability = min(1.0, total_pa / 60.0)
    return weighted_ops / total_weight, reliability, total_pa


def calculate_experimental_probability(
    official_probabilities,
    matchup_data=None,
    batter_pitcher_matchups=None,
):
    """Calculate a separate, bounded pregame probability for research comparison.

    Starts from the official probability and applies conservative, documented
    context adjustments. Missing factors contribute zero and are reported as
    unavailable; they are never interpreted as negative evidence.
    """
    official = _number((official_probabilities or {}).get("home"))
    if official is None:
        official = 0.5
    official = max(MIN_PROBABILITY, min(MAX_PROBABILITY, official))
    matchup_data = matchup_data if isinstance(matchup_data, dict) else {}
    bvp = batter_pitcher_matchups if isinstance(batter_pitcher_matchups, dict) else {}

    adjustments = []
    components = {}
    available_count = 0

    def add_component(name, signal, max_impact, details):
        nonlocal available_count
        if signal is None:
            components[name] = {"available": False, "adjustment": 0.0, **details}
            return
        signal = _clamp(signal)
        adjustment = signal * max_impact
        adjustments.append(adjustment)
        available_count += 1
        components[name] = {
            "available": True,
            "signal": round(signal, 4),
            "adjustment": round(adjustment, 4),
            **details,
        }

    # Head-to-head history: require at least three completed games.
    h2h = matchup_data.get("h2h") or {}
    h2h_games = int(_number(h2h.get("games")) or 0)
    home_wins = _number(h2h.get("home_team_wins"))
    away_wins = _number(h2h.get("away_team_wins"))
    if h2h.get("available") and h2h_games >= 3 and home_wins is not None and away_wins is not None:
        h2h_signal = _bounded_signal((home_wins - away_wins) / h2h_games, 0.55)
    else:
        h2h_signal = None
    add_component("h2h", h2h_signal, 0.025, {"games": h2h_games})

    # Team OPS splits versus the opposing starter's throwing hand.
    splits = matchup_data.get("batting_splits") or {}
    home_split = (splits.get("home_team") or {}).get("batting_split") or {}
    away_split = (splits.get("away_team") or {}).get("batting_split") or {}
    home_ops = _number(home_split.get("ops"))
    away_ops = _number(away_split.get("ops"))
    if home_split.get("available") and away_split.get("available") and home_ops is not None and away_ops is not None:
        split_signal = _bounded_signal(home_ops - away_ops, 0.18)
    else:
        split_signal = None
    add_component("batting_splits", split_signal, 0.025, {
        "home_ops": home_ops,
        "away_ops": away_ops,
    })

    # Bullpen signal is explicitly oriented: positive means home advantage.
    bullpen = matchup_data.get("bullpen") or {}
    bullpen_signal = _number(bullpen.get("signal"))
    bullpen_confidence = _number(bullpen.get("confidence"))
    if bullpen.get("available") and bullpen_signal is not None:
        reliability = _clamp(bullpen_confidence if bullpen_confidence is not None else 0.0, 0.0, 1.0)
        bullpen_signal *= reliability
    else:
        bullpen_signal = None
        reliability = 0.0
    add_component("bullpen", bullpen_signal, 0.020, {"confidence": reliability})

    # Batter-vs-pitcher is only used when both lineups are confirmed by MLB.
    home_team = bvp.get("home_team") or {}
    away_team = bvp.get("away_team") or {}
    home_bvp_ops, home_bvp_reliability, home_pa = _bvp_lineup_signal(home_team)
    away_bvp_ops, away_bvp_reliability, away_pa = _bvp_lineup_signal(away_team)
    if home_bvp_ops is not None and away_bvp_ops is not None:
        raw_bvp_signal = _bounded_signal(home_bvp_ops - away_bvp_ops, 0.45)
        bvp_signal = raw_bvp_signal * min(home_bvp_reliability, away_bvp_reliability)
    else:
        bvp_signal = None
    add_component("batter_vs_pitcher", bvp_signal, 0.015, {
        "home_lineup_confirmed": bool(home_team.get("lineup_confirmed")),
        "away_lineup_confirmed": bool(away_team.get("lineup_confirmed")),
        "home_sample_pa": home_pa,
        "away_sample_pa": away_pa,
    })

    total_adjustment = sum(adjustments)
    experimental_home = max(
        MIN_PROBABILITY,
        min(MAX_PROBABILITY, official + total_adjustment),
    )
    experimental_home = round(experimental_home, 4)
    experimental_away = round(1.0 - experimental_home, 4)

    return {
        "version": EXPERIMENTAL_VERSION,
        "status": "research_only",
        "label": "Probabilidad experimental — en evaluación",
        "home_probability": experimental_home,
        "away_probability": experimental_away,
        "home_adjustment": round(experimental_home - official, 4),
        "official_home_probability": round(official, 4),
        "available_components": available_count,
        "total_components": 4,
        "components": components,
        "method": (
            "Ajustes heurísticos provisionales sobre la probabilidad oficial; "
            "no calibrados ni validados como superiores. Datos ausentes no aportan señal."
        ),
    }
