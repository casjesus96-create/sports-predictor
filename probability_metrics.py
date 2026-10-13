"""Metrics for evaluating the quality of saved MLB win probabilities."""

import math


def calculate_probability_metrics(rows):
    """Evaluate settled predictions; lower Brier score and log loss are better."""
    brier_scores = []
    log_losses = []

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

        clipped = min(max(probability, 1e-15), 1 - 1e-15)
        brier_scores.append((probability - actual_home_win) ** 2)
        log_losses.append(-math.log(clipped if actual_home_win else 1 - clipped))

    count = len(brier_scores)
    return {
        "sample_size": count,
        "brier_score": round(sum(brier_scores) / count, 6) if count else None,
        "log_loss": round(sum(log_losses) / count, 6) if count else None,
    }
