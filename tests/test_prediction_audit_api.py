from prediction_audit_api import audit_settled_row


def valid_row():
    return {
        "sport": "MLB",
        "league": "MLB",
        "model_version": "2.0.0-matchup",
        "home_probability": 0.61,
        "away_probability": 0.39,
        "actual_home_score": 5,
        "actual_away_score": 3,
        "settled_at": "2026-10-20T22:00:00+00:00",
    }


def test_valid_settled_row_has_no_issues():
    assert audit_settled_row(valid_row()) == []


def test_missing_model_version_is_flagged():
    row = valid_row()
    row["model_version"] = None
    assert "MISSING_MODEL_VERSION" in audit_settled_row(row)


def test_invalid_probabilities_are_flagged():
    row = valid_row()
    row["home_probability"] = 1.2
    assert "INVALID_PROBABILITIES" in audit_settled_row(row)


def test_non_complementary_probabilities_are_flagged():
    row = valid_row()
    row["home_probability"] = 0.6
    row["away_probability"] = 0.6
    assert "PROBABILITIES_NOT_COMPLEMENTARY" in audit_settled_row(row)


def test_missing_score_and_settlement_time_are_flagged():
    row = valid_row()
    row["actual_home_score"] = None
    row["settled_at"] = None
    issues = audit_settled_row(row)
    assert "MISSING_OR_INVALID_FINAL_SCORE" in issues
    assert "MISSING_SETTLED_AT" in issues


def test_unknown_sport_is_flagged():
    row = valid_row()
    row["sport"] = "HOCKEY"
    row["league"] = "HOCKEY"
    assert "MISSING_OR_UNKNOWN_SPORT" in audit_settled_row(row)
