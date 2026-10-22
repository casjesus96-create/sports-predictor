from decision_audit_coverage import build_decision_audit_coverage


def test_coverage_separates_manual_pending_settled_and_missing_links():
    evaluations = [
        {"id": "e1", "sport": "MLB", "model_version": "2.0.0-matchup", "prediction_snapshot_id": None},
        {"id": "e2", "sport": "MLB", "model_version": "2.0.0-matchup", "prediction_snapshot_id": "pending", "selected_side": "home"},
        {"id": "e3", "sport": "MLB", "model_version": "2.0.0-matchup", "prediction_snapshot_id": "settled", "selected_side": "away"},
        {"id": "e4", "sport": "MLB", "model_version": "2.0.0-matchup", "prediction_snapshot_id": "missing", "selected_side": "home"},
        {"id": "e5", "sport": "MLB", "model_version": "2.0.0-matchup", "prediction_snapshot_id": "bad-score", "selected_side": "home"},
    ]
    snapshots = [
        {"id": "pending", "result_status": "PENDING"},
        {"id": "settled", "result_status": "SETTLED", "actual_home_score": 2, "actual_away_score": 4},
        {"id": "bad-score", "result_status": "SETTLED", "actual_home_score": None, "actual_away_score": None},
    ]
    report = build_decision_audit_coverage(evaluations, snapshots)
    coverage = report["coverage"]
    assert coverage["total_evaluations"] == 5
    assert coverage["manual_evaluations"] == 1
    assert coverage["linked_evaluations"] == 4
    assert coverage["missing_source_snapshot"] == 1
    assert coverage["source_pending"] == 1
    assert coverage["source_settled"] == 2
    assert coverage["settled_audit_eligible"] == 1
    assert coverage["settled_missing_valid_score"] == 1


def test_coverage_ignores_other_sports():
    report = build_decision_audit_coverage(
        [{"sport": "NBA", "prediction_snapshot_id": None}],
        [],
    )
    assert report["coverage"]["total_evaluations"] == 0
    assert report["by_model"] == []
