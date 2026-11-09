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
    assert calibration["outcomes"]["home"]["brier_score"] == 0.25333
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
