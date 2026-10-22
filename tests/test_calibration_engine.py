from calibration_engine import build_calibration_report


def test_calibration_groups_probabilities_and_outcomes():
    rows = [
        {"sport": "basketball", "model_version": "NBA-1.1.0", "home_probability": 0.62,
         "away_probability": 0.38, "actual_home_score": 110, "actual_away_score": 100},
        {"sport": "basketball", "model_version": "NBA-1.1.0", "home_probability": 0.68,
         "away_probability": 0.32, "actual_home_score": 95, "actual_away_score": 101},
    ]
    report = build_calibration_report(rows)
    group = report["groups"][0]
    assert group["model_status"] == "OFFICIAL"
    assert group["sample_size"] == 2
    assert group["bins"][0]["range"] == "60%-70%"
    assert group["bins"][0]["mean_predicted_probability"] == 0.65
    assert group["bins"][0]["observed_home_win_rate"] == 0.5
    assert group["bins"][0]["calibration_gap_percentage_points"] == -15.0
    assert group["sample_warning"] is not None


def test_calibration_excludes_ties_invalid_probabilities_and_inconsistent_pairs():
    rows = [
        {"sport": "NBA", "model_version": "NBA-1.1.0", "home_probability": 0.6,
         "away_probability": 0.4, "actual_home_score": 100, "actual_away_score": 100},
        {"sport": "NBA", "model_version": "NBA-1.1.0", "home_probability": 0.6,
         "away_probability": 0.5, "actual_home_score": 100, "actual_away_score": 90},
        {"sport": "NBA", "model_version": "NBA-1.1.0", "home_probability": None,
         "away_probability": 0.4, "actual_home_score": 100, "actual_away_score": 90},
    ]
    report = build_calibration_report(rows)
    assert report["groups"] == []
    assert report["settled_rows_excluded"] == 3


def test_calibration_marks_non_official_models_as_historical():
    rows = [
        {"sport": "MLB", "model_version": "1.2.0-form", "home_probability": 0.55,
         "away_probability": 0.45, "actual_home_score": 4, "actual_away_score": 2},
    ]
    report = build_calibration_report(rows)
    assert report["groups"][0]["model_status"] == "HISTORICAL"
