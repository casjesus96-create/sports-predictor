from decision_value_integrity_audit import build_decision_value_integrity_audit


def test_integrity_audit_checks_ev_and_selected_side_snapshot_probability():
    evaluations = [
        {
            "id": "e1", "sport": "MLB", "model_version": "2.0.0-matchup",
            "prediction_snapshot_id": "s1", "selected_side": "away",
            "selected_team": "Away", "model_probability": 0.55,
            "decimal_odds": 2.0, "expected_value_percent": 10.0,
        },
        {
            "id": "e2", "sport": "MLB", "model_version": "2.0.0-matchup",
            "prediction_snapshot_id": "s2", "selected_side": "home",
            "selected_team": "Home", "model_probability": 0.60,
            "decimal_odds": 2.0, "expected_value_percent": 25.0,
        },
    ]
    snapshots = [
        {"id": "s1", "home_probability": 0.45, "away_probability": 0.55},
        {"id": "s2", "home_probability": 0.50, "away_probability": 0.50},
    ]
    report = build_decision_value_integrity_audit(evaluations, snapshots)
    audit = report["audit"]
    assert audit["evaluations_examined"] == 2
    assert audit["ev_matches_formula"] == 2
    assert audit["probability_matches_snapshot"] == 1
    assert audit["probability_mismatches_snapshot"] == 1
    assert report["recent_evaluations"][0]["status"] == "CONSISTENT"
    assert report["recent_evaluations"][1]["status"] == "SNAPSHOT_PROBABILITY_MISMATCH"


def test_integrity_audit_detects_wrong_ev_and_missing_snapshot():
    evaluations = [
        {
            "id": "e1", "sport": "MLB", "model_version": "2.0.0-matchup",
            "prediction_snapshot_id": "missing", "selected_side": "home",
            "model_probability": 0.55, "decimal_odds": 2.0,
            "expected_value_percent": 5.0,
        },
        {
            "id": "e2", "sport": "MLB", "model_version": None,
            "prediction_snapshot_id": None, "selected_side": "manual",
            "model_probability": 0.50, "decimal_odds": 2.0,
            "expected_value_percent": 0.0,
        },
    ]
    report = build_decision_value_integrity_audit(evaluations, [])
    audit = report["audit"]
    assert audit["missing_snapshot"] == 1
    assert audit["ev_mismatches_formula"] == 1
    assert audit["manual_evaluations"] == 1
    assert report["recent_evaluations"][0]["status"] == "EV_MISMATCH"


def test_integrity_audit_ignores_other_sports():
    report = build_decision_value_integrity_audit(
        [{"sport": "NBA", "model_probability": 0.5, "decimal_odds": 2, "expected_value_percent": 0}],
        [],
    )
    assert report["audit"]["evaluations_examined"] == 0
    assert report["by_model"] == []
