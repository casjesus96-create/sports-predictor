import pytest

from mlb_hit_projection_backtest import evaluate_live_hit_forecasts


def test_evaluates_probability_metrics_and_calibration():
    report = evaluate_live_hit_forecasts([
        {"probability_additional_hit": 0.8, "actual_additional_hit": True},
        {"probability_additional_hit": 0.2, "actual_additional_hit": False},
        {"probability_additional_hit": 0.7, "actual_additional_hit": True},
        {"probability_additional_hit": 0.1, "actual_additional_hit": False},
    ], bins=5)

    assert report["n"] == 4
    assert report["excluded_rows"] == 0
    assert report["primary"]["observed_hit_rate"] == 0.5
    assert report["primary"]["brier_score"] == 0.045
    assert report["primary"]["log_loss"] is not None
    assert sum(item["n"] for item in report["primary"]["calibration"]) == 4


def test_compares_primary_and_season_average_baseline_on_paired_rows():
    report = evaluate_live_hit_forecasts([
        {"probability_additional_hit": 0.8, "baseline_probability": 0.6, "actual_additional_hit": 1},
        {"probability_additional_hit": 0.2, "baseline_probability": 0.4, "actual_additional_hit": 0},
        {"probability_additional_hit": 0.7, "baseline_probability": 0.6, "actual_additional_hit": 1},
        {"probability_additional_hit": 0.1, "baseline_probability": 0.4, "actual_additional_hit": 0},
        {"probability_additional_hit": 0.5, "actual_additional_hit": 1},
    ])

    assert report["n"] == 5
    assert report["baseline"]["n"] == 4
    assert report["comparison"]["paired_n"] == 4
    assert report["comparison"]["primary_brier_minus_baseline"] < 0


def test_excludes_invalid_rows_and_probabilities():
    report = evaluate_live_hit_forecasts([
        {"probability_additional_hit": 1.2, "actual_additional_hit": 1},
        {"probability_additional_hit": 0.5, "actual_additional_hit": "unknown"},
        {"probability_additional_hit": 0.6, "actual_additional_hit": 1},
        None,
    ])

    assert report["n"] == 1
    assert report["excluded_rows"] == 3
    assert report["primary"]["brier_score"] == 0.16


def test_rejects_invalid_bin_count():
    with pytest.raises(ValueError):
        evaluate_live_hit_forecasts([], bins=0)
