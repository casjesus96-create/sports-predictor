"""Metrics for evaluating the quality and calibration of saved MLB win probabilities."""

import math

CALIBRATION_BIN_COUNT = 5


def _valid_settled_outcomes(rows):
    """Yield (home-win probability, observed home win) for valid settled rows."""
    for row in rows or []:
        if str(row.get("result_status") or "").upper() != "SETTLED":
            continue

        game = ((row.get("features") or {}).get("game") or {})
        home_name = str(game.get("home") or "").strip().casefold()
        away_name = str(game.get("away") or "").strip().casefold()
        actual_winner = str(row.get("actual_winner") or "").strip().casefold()

        if not home_name or not away_name or not actual_winner:
            continue
        if actual_winner == home_name:
            actual_home_win = 1
        elif actual_winner == away_name:
            actual_home_win = 0
        else:
            continue

        try:
            probability = float(row.get("home_probability"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            continue

        yield probability, actual_home_win


def calculate_calibration_bins(rows, bin_count=CALIBRATION_BIN_COUNT):
    """
    Group valid settled predictions into equal-width probability bins.

    The last bin includes probability 1.0. Each bin reports the mean
    forecast probability and the observed home-win frequency. These are
    descriptive diagnostics, not a model-quality guarantee; small samples
    can be noisy.
    """
    if not isinstance(bin_count, int) or isinstance(bin_count, bool) or bin_count < 1:
        raise ValueError("bin_count must be a positive integer")

    buckets = [[] for _ in range(bin_count)]
    for probability, actual_home_win in _valid_settled_outcomes(rows):
        index = min(int(probability * bin_count), bin_count - 1)
        buckets[index].append((probability, actual_home_win))

    results = []
    for index, values in enumerate(buckets):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        count = len(values)
        results.append({
            "range": f"{lower:.2f}-{upper:.2f}",
            "lower_bound": round(lower, 4),
            "upper_bound": round(upper, 4),
            "sample_size": count,
            "mean_predicted_probability": (
                round(sum(probability for probability, _ in values) / count, 6)
                if count else None
            ),
            "observed_home_win_rate": (
                round(sum(actual for _, actual in values) / count, 6)
                if count else None
            ),
        })

    return results


def calculate_probability_metrics(rows):
    """Evaluate settled predictions; lower Brier score and log loss are better."""
    brier_scores = []
    log_losses = []

    for probability, actual_home_win in _valid_settled_outcomes(rows):
        clipped = min(max(probability, 1e-15), 1 - 1e-15)
        brier_scores.append((probability - actual_home_win) ** 2)
        log_losses.append(-math.log(clipped if actual_home_win else 1 - clipped))

    count = len(brier_scores)
    return {
        "sample_size": count,
        "brier_score": round(sum(brier_scores) / count, 6) if count else None,
        "log_loss": round(sum(log_losses) / count, 6) if count else None,
        "calibration_bins": calculate_calibration_bins(rows),
    }
