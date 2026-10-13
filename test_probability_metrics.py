import math

from probability_metrics import calculate_probability_metrics


def row(status, probability, actual, home="Home", away="Away"):
    return {
        "result_status": status,
        "home_probability": probability,
        "actual_winner": actual,
        "features": {"game": {"home": home, "away": away}},
    }


def test_brier_and_log_loss_for_settled_predictions():
    result = calculate_probability_metrics([
        row("SETTLED", 0.8, "Home"),
        row("SETTLED", 0.2, "Away"),
    ])
    assert result["sample_size"] == 2
    assert result["brier_score"] == 0.04
    assert result["log_loss"] == round(-math.log(0.8), 6)


def test_pending_predictions_are_not_evaluated():
    assert calculate_probability_metrics([row("PENDING", 0.9, "Home")]) == {
        "sample_size": 0,
        "brier_score": None,
        "log_loss": None,
    }


def test_unknown_winner_and_invalid_probability_are_skipped():
    result = calculate_probability_metrics([
        row("SETTLED", 0.7, "Unknown"),
        row("SETTLED", float("nan"), "Home"),
        row("SETTLED", 1.1, "Home"),
        row("SETTLED", None, "Away"),
    ])
    assert result["sample_size"] == 0
    assert result["brier_score"] is None
    assert result["log_loss"] is None


def test_team_name_matching_is_case_insensitive():
    result = calculate_probability_metrics([row("SETTLED", 0.75, "hOmE")])
    assert result["sample_size"] == 1
    assert result["brier_score"] == 0.0625
