import math

import pytest

from probability_metrics import (
    calculate_calibration_bins,
    calculate_probability_metrics,
)


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
    assert len(result["calibration_bins"]) == 5
    assert result["calibration_bins"][0]["sample_size"] == 1
    assert result["calibration_bins"][0]["mean_predicted_probability"] == 0.2
    assert result["calibration_bins"][0]["observed_home_win_rate"] == 0.0
    assert result["calibration_bins"][4]["sample_size"] == 1
    assert result["calibration_bins"][4]["observed_home_win_rate"] == 1.0


def test_pending_predictions_are_not_evaluated():
    result = calculate_probability_metrics([row("PENDING", 0.9, "Home")])
    assert result["sample_size"] == 0
    assert result["brier_score"] is None
    assert result["log_loss"] is None
    assert all(bucket["sample_size"] == 0 for bucket in result["calibration_bins"])
    assert all(bucket["mean_predicted_probability"] is None for bucket in result["calibration_bins"])


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
    assert all(bucket["sample_size"] == 0 for bucket in result["calibration_bins"])


def test_team_name_matching_is_case_insensitive():
    result = calculate_probability_metrics([row("SETTLED", 0.75, "hOmE")])
    assert result["sample_size"] == 1
    assert result["brier_score"] == 0.0625


def test_probability_one_is_included_in_last_bin():
    bins = calculate_calibration_bins([row("SETTLED", 1.0, "Home")])
    assert bins[-1]["sample_size"] == 1
    assert bins[-1]["mean_predicted_probability"] == 1.0


def test_calibration_ignores_unsettled_and_unknown_results():
    bins = calculate_calibration_bins([
        row("PENDING", 0.4, "Home"),
        row("SETTLED", 0.4, "Not a team"),
    ])
    assert sum(bucket["sample_size"] for bucket in bins) == 0


def test_invalid_bin_count_is_rejected():
    with pytest.raises(ValueError):
        calculate_calibration_bins([], bin_count=0)
