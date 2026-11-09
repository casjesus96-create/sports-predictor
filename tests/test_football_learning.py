from football_learning import build_postmatch_learning_report
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
