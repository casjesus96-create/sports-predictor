from football_learning import build_match_learning_context, build_postmatch_learning_report
from football_model import MODEL_VERSION


def snapshot(home_p, draw_p, away_p, actual_home, actual_away, match_id=1):
    outcome = "HOME" if actual_home > actual_away else "AWAY" if actual_home < actual_away else "DRAW"
    return {
        "provider_match_id": match_id,
        "competition_code": "PL",
        "kickoff_at": "2026-11-08T15:00:00Z",
        "home_team": "Manchester City",
        "away_team": "Chelsea",
        "model_version": MODEL_VERSION,
        "home_probability": home_p,
        "draw_probability": draw_p,
        "away_probability": away_p,
        "expected_goals": {"home": 2.0, "away": 1.0, "total": 3.0},
        "prediction_payload": {
            "goal_markets": {
                "both_teams_to_score": {"yes": {"probability": 0.6}},
                "total_goals": {"over_2_5": {"probability": 0.55}},
            }
        },
        "result_status": "SETTLED",
        "actual_home_score": actual_home,
        "actual_away_score": actual_away,
        "actual_outcome": outcome,
    }


def test_postmatch_learning_flags_upset_and_keeps_official_model_read_only():
    row = snapshot(0.72, 0.18, 0.10, 0, 2)
    report = build_postmatch_learning_report([row], "PL")

    assert report["success"] is True
    assert report["read_only"] is True
    assert report["model_version"] == MODEL_VERSION
    assert report["model_changed"] is False
    assert report["snapshots_written"] == 0
    assert report["metrics"]["upset_count"] == 1
    assert report["surprises"][0]["home_team"] == "Manchester City"
    assert report["surprises"][0]["actual_outcome"] == "AWAY"


def test_postmatch_learning_scores_goals_markets_and_expected_goals():
    row = snapshot(0.60, 0.25, 0.15, 2, 1)
    report = build_postmatch_learning_report([row], "PL")

    assert report["metrics"]["expected_total_goals_mae"] == 0.0
    assert report["metrics"]["btts_sample"] == 1
    assert report["metrics"]["over_2_5_sample"] == 1
    assert report["metrics"]["btts_brier_score"] == 0.16
    assert report["metrics"]["over_2_5_brier_score"] == 0.2025


def test_postmatch_learning_excludes_invalid_probability_rows():
    row = snapshot(0.8, 0.3, 0.1, 1, 0)
    report = build_postmatch_learning_report([row], "PL")

    assert report["sample_size"] == 0
    assert report["excluded_invalid_rows"] == 1
    assert report["read_only"] is True
    assert report["model_changed"] is False
    assert report["snapshots_written"] == 0
    assert report["provider_calls"] == 0



def test_match_learning_context_excludes_same_time_and_future_snapshots():
    cutoff = "2026-11-15T12:00:00Z"
    previous = snapshot(0.60, 0.25, 0.15, 2, 1, 10)
    previous["kickoff_at"] = "2026-11-08T15:00:00+00:00"
    same_time = snapshot(0.80, 0.10, 0.10, 1, 0, 11)
    same_time["kickoff_at"] = cutoff
    future = snapshot(0.80, 0.10, 0.10, 1, 0, 12)
    future["kickoff_at"] = "2026-11-16T15:00:00Z"

    report = build_match_learning_context(
        [previous, same_time, future], "PL", "Manchester City", "Chelsea", cutoff
    )

    assert report["competition_context"]["sample_size"] == 1
    assert report["home_team"]["sample_size"] == 1
    assert report["away_team"]["sample_size"] == 1
    assert report["model_changed"] is False
    assert report["snapshots_written"] == 0
    assert report["provider_calls"] == 0


def test_match_learning_context_requires_minimum_team_sample():
    rows = []
    for index in range(5):
        row = snapshot(0.60, 0.25, 0.15, 2, 1, index + 20)
        row["kickoff_at"] = f"2026-11-{index + 1:02d}T15:00:00Z"
        rows.append(row)

    report = build_match_learning_context(
        rows, "PL", "Manchester City", "Chelsea", "2026-11-15T12:00:00Z"
    )

    assert report["home_team"]["sample_size"] == 5
    assert report["home_team"]["eligible"] is True
    assert report["away_team"]["eligible"] is True
    assert report["competition_context"]["eligible"] is False


def test_low_confidence_miss_is_not_counted_as_favorite_upset():
    row = snapshot(0.43, 0.32, 0.25, 0, 1)
    report = build_postmatch_learning_report([row], "PL")
    low_band = next(item for item in report["confidence_bands"] if item["range"] == "0–50%")

    assert low_band["misses"] == 1
    assert low_band["upsets"] == 0
    assert report["metrics"]["upset_count"] == 0


def test_binary_market_calibration_scores_and_bins():
    rows = [snapshot(0.60, 0.25, 0.15, 2, 1), snapshot(0.60, 0.25, 0.15, 0, 1, 2)]
    for row in rows:
        row["prediction_payload"]["goal_markets"]["both_teams_to_score"]["yes"]["probability"] = 0.8
        row["prediction_payload"]["goal_markets"]["total_goals"]["over_2_5"]["probability"] = 0.7
    report = build_postmatch_learning_report(rows, "PL")
    btts = report["market_calibration"]["btts_yes"]
    over25 = report["market_calibration"]["over_2_5"]
    assert btts["sample_size"] == 2
    assert btts["brier_score"] == 0.34
    assert btts["calibration_bins"][-1]["observed_rate"] == 0.5
    assert over25["sample_size"] == 2
    assert over25["brier_score"] == 0.29
    assert report["model_changed"] is False


def test_market_calibration_excludes_invalid_probabilities():
    row = snapshot(0.6, 0.25, 0.15, 2, 1)
    row["prediction_payload"]["goal_markets"]["both_teams_to_score"]["yes"]["probability"] = 1.2
    report = build_postmatch_learning_report([row], "PL")
    market = report["market_calibration"]["btts_yes"]
    assert market["sample_size"] == 0
    assert market["brier_score"] is None



def test_1x2_calibration_reports_multiclass_and_each_outcome_separately():
    rows = [
        snapshot(0.60, 0.25, 0.15, 2, 0, 101),
        snapshot(0.60, 0.25, 0.15, 1, 1, 102),
        snapshot(0.60, 0.25, 0.15, 0, 2, 103),
    ]
    report = build_postmatch_learning_report(rows, "PL")
    calibration = report["outcome_calibration"]

    assert calibration["sample_size"] == 3
    assert calibration["multiclass_brier_score"] == report["metrics"]["brier_score"]
    assert calibration["multiclass_log_loss"] == report["metrics"]["log_loss"]
    assert calibration["outcomes"]["home"]["sample_size"] == 3
    assert calibration["outcomes"]["home"]["brier_score"] == 0.29333
    assert calibration["outcomes"]["home"]["calibration_bins"][2]["observed_rate"] == 0.3333
    assert calibration["outcomes"]["draw"]["sample_size"] == 3
    assert calibration["outcomes"]["away"]["sample_size"] == 3
    assert report["model_changed"] is False
    assert report["snapshots_written"] == 0
    assert report["provider_calls"] == 0


def test_1x2_calibration_has_stable_empty_schema():
    report = build_postmatch_learning_report([], "PL")
    calibration = report["outcome_calibration"]

    assert calibration["sample_size"] == 0
    assert calibration["multiclass_brier_score"] is None
    assert calibration["multiclass_log_loss"] is None
    assert set(calibration["outcomes"]) == {"home", "draw", "away"}
    assert all(item["sample_size"] == 0 for item in calibration["outcomes"].values())



def test_segmented_calibration_uses_competition_local_july_to_june_season():
    from football_learning import _football_season

    assert _football_season("2026-07-01T00:30:00Z", "PL") == "2026/27"
    assert _football_season("2026-06-30T22:30:00Z", "PD") == "2026/27"
    assert _football_season("2026-06-30T22:00:00Z", "PL") == "2025/26"
    assert _football_season("2026-11-08T15:00:00", "PL") is None
    assert _football_season("2026-11-08T15:00:00Z", "XYZ") is None


def test_segmented_calibration_requires_30_observations_per_segment_and_metric():
    rows = []
    for index in range(30):
        row = snapshot(0.60, 0.25, 0.15, 2, 1, 500 + index)
        year = 2024 if index < 15 else 2025
        day = (index % 15) + 1
        row["kickoff_at"] = f"{year}-09-{day:02d}T15:00:00Z"
        row["competition_code"] = "PL"
        if index >= 28:
            row["prediction_payload"]["goal_markets"]["both_teams_to_score"]["yes"]["probability"] = None
        rows.append(row)

    report = build_postmatch_learning_report(rows, "PL")
    segmented = report["segmented_calibration"]

    assert segmented["minimum_sample"] == 30
    assert len(segmented["by_competition"]) == 1
    competition = segmented["by_competition"][0]
    assert competition["sample_size"] == 30
    assert competition["eligible"] is True
    assert competition["metrics"]["accuracy"] == 1.0
    assert competition["outcomes"]["home"]["sample_size"] == 30
    assert competition["outcomes"]["home"]["eligible"] is True
    assert competition["markets"]["btts_yes"]["sample_size"] == 28
    assert competition["markets"]["btts_yes"]["eligible"] is False
    assert competition["markets"]["btts_yes"]["metrics"] is None
    assert len(segmented["by_season"]) == 2
    assert all(item["sample_size"] == 15 for item in segmented["by_season"])
    assert all(item["eligible"] is False for item in segmented["by_season"])
    assert all(item["metrics"] is None for item in segmented["by_season"])
    assert report["model_changed"] is False
    assert report["snapshots_written"] == 0
    assert report["provider_calls"] == 0


def test_segmented_calibration_keeps_competitions_separate():
    rows = []
    for index in range(30):
        row = snapshot(0.60, 0.25, 0.15, 2, 1, 700 + index)
        row["competition_code"] = "PL" if index < 15 else "BL1"
        row["kickoff_at"] = f"2025-09-{(index % 15) + 1:02d}T15:00:00Z"
        rows.append(row)

    report = build_postmatch_learning_report(rows)
    by_competition = {item["competition"]: item for item in report["segmented_calibration"]["by_competition"]}

    assert set(by_competition) == {"PL", "BL1"}
    assert by_competition["PL"]["sample_size"] == 15
    assert by_competition["BL1"]["sample_size"] == 15
    assert by_competition["PL"]["eligible"] is False
    assert by_competition["BL1"]["eligible"] is False


def test_empty_report_has_stable_segmented_calibration_schema():
    report = build_postmatch_learning_report([], "PL")
    segmented = report["segmented_calibration"]

    assert segmented["minimum_sample"] == 30
    assert segmented["by_competition"] == []
    assert segmented["by_season"] == []
    assert segmented["read_only"] is True
    assert segmented["model_changed"] is False



def test_error_diagnostics_build_confusion_matrix_and_goal_residuals():
    rows = []
    for index in range(30):
        # Predicted HOME, actual DRAW: the model's most likely outcome is wrong.
        row = snapshot(0.60, 0.25, 0.15, 1, 1, 900 + index)
        row["expected_goals"] = {"home": 1.5, "away": 0.8, "total": 2.3}
        rows.append(row)

    report = build_postmatch_learning_report(rows, "PL")
    diagnostic = report["error_diagnostics"]
    matrix = diagnostic["confusion_matrix"]["predicted_rows_actual_columns"]

    assert matrix["HOME"]["DRAW"] == 30
    assert matrix["HOME"]["HOME"] == 0
    assert diagnostic["goal_residuals"]["home_goals"]["sample_size"] == 30
    assert diagnostic["goal_residuals"]["home_goals"]["bias_actual_minus_expected"] == -0.5
    assert diagnostic["goal_residuals"]["home_goals"]["mae"] == 0.5
    assert diagnostic["goal_residuals"]["away_goals"]["bias_actual_minus_expected"] == 0.2
    assert diagnostic["goal_residuals"]["total_goals"]["bias_actual_minus_expected"] == -0.3
    assert diagnostic["read_only"] is True
    assert diagnostic["model_changed"] is False
    assert report["snapshots_written"] == 0
    assert report["provider_calls"] == 0



def test_segmented_error_diagnostics_group_by_competition_and_local_season():
    rows = []
    for index in range(30):
        row = snapshot(0.60, 0.25, 0.15, 1, 1, 1200 + index)
        row["kickoff_at"] = f"2026-08-{(index % 28) + 1:02d}T15:00:00Z"
        row["expected_goals"] = {"home": 1.5, "away": 0.8, "total": 2.3}
        rows.append(row)

    report = build_postmatch_learning_report(rows, "PL")
    segmented = report["segmented_error_diagnostics"]

    assert segmented["minimum_sample"] == 30
    assert len(segmented["by_competition"]) == 1
    assert segmented["by_competition"][0]["competition"] == "PL"
    assert segmented["by_competition"][0]["sample_size"] == 30
    assert segmented["by_competition"][0]["eligible"] is True
    assert segmented["by_competition"][0]["confusion_matrix"]["HOME"]["DRAW"] == 30
    assert len(segmented["by_season"]) == 1
    assert segmented["by_season"][0]["season"] == "2026/27"
    assert segmented["by_season"][0]["goal_residuals"]["home_goals"]["bias_actual_minus_expected"] == -0.5
    assert segmented["read_only"] is True
    assert segmented["model_changed"] is False


def test_segmented_error_diagnostics_keep_small_samples_descriptive_only():
    rows = []
    for index in range(29):
        row = snapshot(0.60, 0.25, 0.15, 2, 1, 1300 + index)
        row["kickoff_at"] = f"2026-08-{(index % 28) + 1:02d}T15:00:00Z"
        rows.append(row)

    segmented = build_postmatch_learning_report(rows, "PL")["segmented_error_diagnostics"]
    segment = segmented["by_competition"][0]
    assert segment["sample_size"] == 29
    assert segment["eligible"] is False
    assert segment["goal_residuals"]["home_goals"]["bias_actual_minus_expected"] is None


def test_segmented_error_diagnostics_excludes_unknown_competition_or_season():
    row = snapshot(0.60, 0.25, 0.15, 2, 1)
    row["competition_code"] = "UNKNOWN"
    segmented = build_postmatch_learning_report([row], None)["segmented_error_diagnostics"]
    assert segmented["by_competition"] == []
    assert segmented["by_season"] == []
    assert segmented["excluded_missing_competition_or_season"] == 1



def test_temporal_error_stability_splits_chronologically_without_splitting_local_dates():
    rows = []
    for index in range(60):
        day = index + 1
        if day <= 31:
            date = f"2026-08-{day:02d}"
        else:
            date = f"2026-09-{day - 31:02d}"
        row = snapshot(0.60, 0.25, 0.15, 1, 1, 1500 + index)
        row["kickoff_at"] = f"{date}T15:00:00Z"
        row["expected_goals"] = {"home": 1.5, "away": 0.8, "total": 2.3}
        rows.append(row)

    stability = build_postmatch_learning_report(rows, "PL")["temporal_error_stability"]
    segment = stability["by_competition"][0]
    assert segment["competition"] == "PL"
    assert segment["eligible"] is True
    assert len(segment["windows"]) == 2
    earlier, later = segment["windows"]
    assert earlier["period"] == "earlier"
    assert later["period"] == "later"
    assert earlier["sample_size"] >= 30
    assert later["sample_size"] >= 30
    assert earlier["end_local_date"] < later["start_local_date"]
    assert earlier["goal_residuals"]["home_goals"]["bias_actual_minus_expected"] == -0.5
    assert stability["read_only"] is True
    assert stability["model_changed"] is False


def test_temporal_error_stability_keeps_same_local_date_in_one_window():
    rows = []
    for index in range(62):
        day = index // 2 + 1
        if day <= 31:
            date = f"2026-08-{day:02d}"
        else:
            date = f"2026-09-{day - 31:02d}"
        row = snapshot(0.60, 0.25, 0.15, 2, 1, 1600 + index)
        row["kickoff_at"] = f"{date}T15:00:00Z"
        rows.append(row)

    segment = build_postmatch_learning_report(rows, "PL")["temporal_error_stability"]["by_competition"][0]
    assert segment["eligible"] is True
    earlier, later = segment["windows"]
    assert earlier["end_local_date"] < later["start_local_date"]
    assert earlier["sample_size"] + later["sample_size"] == 62


def test_temporal_error_stability_requires_minimum_sample_in_both_windows():
    rows = []
    for index in range(59):
        date = f"2026-08-{(index % 28) + 1:02d}"
        row = snapshot(0.60, 0.25, 0.15, 2, 1, 1700 + index)
        row["kickoff_at"] = f"{date}T15:00:00Z"
        rows.append(row)

    segment = build_postmatch_learning_report(rows, "PL")["temporal_error_stability"]["by_competition"][0]
    assert segment["eligible"] is False
    assert segment["windows"] == []


def test_goal_residual_metrics_are_hidden_below_minimum_sample():
    rows = [snapshot(0.60, 0.25, 0.15, 2, 1, 950 + index) for index in range(29)]
    report = build_postmatch_learning_report(rows, "PL")
    home = report["error_diagnostics"]["goal_residuals"]["home_goals"]

    assert home["sample_size"] == 29
    assert home["eligible"] is False
    assert home["bias_actual_minus_expected"] is None
    assert home["mae"] is None
    assert home["rmse"] is None


def test_empty_error_diagnostics_have_stable_schema():
    report = build_postmatch_learning_report([], "PL")
    diagnostic = report["error_diagnostics"]

    assert diagnostic["confusion_matrix"]["sample_size"] == 0
    assert set(diagnostic["confusion_matrix"]["predicted_rows_actual_columns"]) == {"HOME", "DRAW", "AWAY"}
    assert diagnostic["goal_residuals"]["total_goals"]["sample_size"] == 0
    assert diagnostic["read_only"] is True


def test_wilson_intervals_are_bounded_and_reflect_sample_size():
    from football_learning import _wilson_interval

    small = _wilson_interval(8, 10)
    large = _wilson_interval(80, 100)
    assert small is not None and large is not None
    assert 0 <= small["lower"] <= small["upper"] <= 1
    assert 0 <= large["lower"] <= large["upper"] <= 1
    assert (small["upper"] - small["lower"]) > (large["upper"] - large["lower"])
    assert _wilson_interval(0, 0) is None

def test_probability_margin_diagnostics_separate_clear_and_narrow_favorites():
    rows = [
        snapshot(0.60, 0.25, 0.15, 2, 1, 4101),  # margin 35 pp, correct
        snapshot(0.43, 0.32, 0.25, 0, 1, 4102),  # margin 11 pp, wrong
        snapshot(0.48, 0.45, 0.07, 0, 0, 4103),  # margin 3 pp, wrong
    ]
    report = build_postmatch_learning_report(rows, "PL")
    diagnostic = report["probability_margin_diagnostics"]
    bands = {item["range"]: item for item in diagnostic["bands"]}
    assert diagnostic["sample_size"] == 3
    assert bands["20–100 pp"]["sample_size"] == 1
    assert bands["20–100 pp"]["accuracy"] == 1.0
    assert bands["20–100 pp"]["mean_margin"] == 0.35
    assert bands["10–20 pp"]["sample_size"] == 1
    assert bands["10–20 pp"]["accuracy"] == 0.0
    assert bands["0–5 pp"]["sample_size"] == 1
    assert bands["5–10 pp"]["sample_size"] == 0
    assert bands["5–10 pp"]["accuracy_ci_95"] is None
    assert diagnostic["accuracy_ci_95"] == {"lower": 0.0615, "upper": 0.7923}
    assert diagnostic["read_only"] is True
    assert diagnostic["model_changed"] is False
    assert report["snapshots_written"] == 0
    assert report["provider_calls"] == 0


def test_probability_margin_diagnostics_has_stable_empty_schema():
    report = build_postmatch_learning_report([], "PL")
    diagnostic = report["probability_margin_diagnostics"]
    assert diagnostic["sample_size"] == 0
    assert diagnostic["accuracy"] is None
    assert diagnostic["accuracy_ci_95"] is None
    assert len(diagnostic["bands"]) == 4
    assert all(item["sample_size"] == 0 for item in diagnostic["bands"])
    assert diagnostic["read_only"] is True
    assert diagnostic["model_changed"] is False


def test_postmatch_confidence_and_market_bins_expose_wilson_intervals():
    rows = [
        snapshot(0.60, 0.25, 0.15, 2, 1, 3001),
        snapshot(0.60, 0.25, 0.15, 0, 1, 3002),
    ]
    for row in rows:
        row["prediction_payload"]["goal_markets"]["both_teams_to_score"]["yes"]["probability"] = 0.8

    report = build_postmatch_learning_report(rows, "PL")
    confidence = next(item for item in report["confidence_bands"] if item["range"] == "60–70%")
    market_bin = report["market_calibration"]["btts_yes"]["calibration_bins"][-1]

    assert confidence["accuracy_ci_95"] == {"lower": 0.0945, "upper": 0.9055}
    assert market_bin["observed_rate_ci_95"] == {"lower": 0.0945, "upper": 0.9055}
    assert report["read_only"] is True
    assert report["model_changed"] is False
    assert report["snapshots_written"] == 0
    assert report["provider_calls"] == 0



def test_match_learning_context_compares_observed_rates_with_wilson_intervals():
    rows = []
    for index in range(30):
        row = snapshot(0.60, 0.25, 0.15, 0, 1, 3000 + index)
        row["kickoff_at"] = f"2026-11-{(index % 7) + 1:02d}T15:00:00Z"
        rows.append(row)

    report = build_match_learning_context(
        rows, "PL", "Manchester City", "Chelsea", "2026-11-15T12:00:00Z"
    )

    league = report["competition_context"]["favorite_calibration"]
    assert league["sample_size"] == 30
    assert league["observed_rate_ci_95"]["upper"] < league["mean_probability"]
    assert league["status"] == "OVERCONFIDENT"

    home = report["home_team"]["win_rate_diagnostic"]
    assert home["status"] == "OVERCONFIDENT"
    assert home["sample_size"] == 30

    away = report["away_team"]["win_rate_diagnostic"]
    assert away["status"] == "UNDERCONFIDENT"
    assert away["observed_rate_ci_95"]["lower"] > away["mean_probability"]

    assert report["read_only"] is True
    assert report["model_changed"] is False
    assert report["snapshots_written"] == 0
    assert report["provider_calls"] == 0


def test_calibration_comparison_requires_minimum_sample_and_reports_overlap():
    from football_learning import _calibration_comparison

    insufficient = _calibration_comparison(0, 9, 0.8, 10)
    assert insufficient["status"] == "INSUFFICIENT_SAMPLE"

    inconclusive = _calibration_comparison(18, 30, 0.7, 10)
    assert inconclusive["status"] == "INCONCLUSIVE"

    overconfident = _calibration_comparison(0, 30, 0.8, 10)
    assert overconfident["status"] == "OVERCONFIDENT"

    underconfident = _calibration_comparison(30, 30, 0.2, 10)
    assert underconfident["status"] == "UNDERCONFIDENT"



def test_surprises_are_classified_by_probability_of_realized_outcome():
    rows = [
        snapshot(0.80, 0.10, 0.10, 0, 1, 8101),  # 10%: high
        snapshot(0.75, 0.15, 0.10, 1, 1, 8102),  # 15%: high
        snapshot(0.60, 0.15, 0.25, 0, 1, 8103),  # 25%: moderate
        snapshot(0.50, 0.35, 0.15, 1, 1, 8104),  # 35%: low / plausible
        snapshot(0.90, 0.05, 0.05, 0, 1, 8105),  # 5%: extreme
    ]

    report = build_postmatch_learning_report(rows, "PL")
    by_id = {item["match_id"]: item for item in report["surprises"]}

    assert by_id[8101]["classification"] == "HIGH"
    assert by_id[8102]["classification"] == "HIGH"
    assert by_id[8103]["classification"] == "MODERATE"
    assert by_id[8104]["classification"] == "LOW"
    assert by_id[8105]["classification"] == "EXTREME"
    assert by_id[8104]["classification_label"] == "Fallo del favorito, resultado plausible"
    assert by_id[8102]["actual_is_draw"] is True
    assert by_id[8103]["favorite_probability_gap"] == 0.35
    assert report["surprise_classification"]["counts"] == {
        "EXTREME": 1, "HIGH": 2, "MODERATE": 1, "LOW": 1
    }
    assert report["surprise_classification"]["sample_size"] == 5
    assert report["surprise_classification"]["read_only"] is True
    assert report["model_changed"] is False


def test_empty_surprise_classification_has_stable_schema():
    report = build_postmatch_learning_report([], "PL")
    assert report["surprise_classification"]["sample_size"] == 0
    assert report["surprise_classification"]["counts"] == {
        "EXTREME": 0, "HIGH": 0, "MODERATE": 0, "LOW": 0
    }
    assert report["surprise_classification"]["model_changed"] is False
