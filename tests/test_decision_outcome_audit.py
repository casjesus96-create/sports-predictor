from decision_outcome_audit import build_decision_outcome_audit


def test_audit_matches_settled_mlb_selection_and_calculates_flat_stake_roi():
    evaluations = [
        {"id": "e1", "prediction_snapshot_id": "s1", "sport": "MLB", "selected_side": "away",
         "model_version": "2.0.0-matchup", "classification": "VALUE_CANDIDATE",
         "model_probability": 0.55, "decimal_odds": 2.0, "expected_value_percent": 10,
         "selected_team": "Away", "evaluated_at": "2026-10-01T12:00:00Z"}
    ]
    snapshots = [
        {"id": "s1", "result_status": "SETTLED", "actual_home_score": 3, "actual_away_score": 4}
    ]
    report = build_decision_outcome_audit(evaluations, snapshots)
    assert report["matched_evaluations"] == 1
    assert report["overall"]["wins"] == 1
    assert report["overall"]["flat_stake_profit_units"] == 1.0
    assert report["positive_ev_subset"]["sample_size"] == 1


def test_audit_excludes_manual_and_pending_evaluations():
    evaluations = [
        {"prediction_snapshot_id": None, "sport": "MLB", "selected_side": "home"},
        {"prediction_snapshot_id": "s2", "sport": "MLB", "selected_side": "home"},
    ]
    snapshots = [
        {"id": "s2", "result_status": "PENDING", "actual_home_score": None, "actual_away_score": None}
    ]
    report = build_decision_outcome_audit(evaluations, snapshots)
    assert report["matched_evaluations"] == 0
    assert report["excluded_evaluations"] == 2
    assert report["overall"]["flat_stake_roi_percentage"] is None
