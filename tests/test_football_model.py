from football_model import MODEL_VERSION, predict_1x2


def match(home, away, hg, ag, status="FINISHED"):
    return {
        "status": status,
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "score": {"fullTime": {"home": hg, "away": ag}},
    }


def sample_matches():
    return [
        match("A", "B", 2, 0),
        match("B", "C", 1, 1),
        match("C", "A", 0, 1),
        match("A", "C", 1, 0),
        match("B", "A", 0, 2),
        match("C", "B", 2, 1),
        match("A", "B", 1, 1),
        match("B", "C", 2, 0),
        match("C", "A", 1, 2),
    ]


def test_probabilities_are_valid_and_sum_to_one():
    result = predict_1x2("A", "B", sample_matches())
    assert result["available"] is True
    probabilities = result["probabilities"]
    assert set(probabilities) == {"home", "draw", "away"}
    assert all(0 <= value <= 1 for value in probabilities.values())
    assert abs(sum(probabilities.values()) - 1) < 1e-5
    assert result["model_version"] == MODEL_VERSION


def test_unfinished_matches_are_ignored():
    matches = sample_matches() + [match("A", "B", 9, 0, status="SCHEDULED")]
    result = predict_1x2("A", "B", matches)
    assert result["available"] is True
    assert result["sample"]["completed_matches_in_competition"] == 9


def test_insufficient_team_history_returns_unavailable():
    result = predict_1x2("A", "Z", sample_matches())
    assert result["available"] is False
    assert "al menos" in result["reason"]


def test_invalid_same_team_raises():
    try:
        predict_1x2("A", "A", sample_matches())
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")


def test_no_finished_matches_returns_unavailable():
    result = predict_1x2("A", "B", [match("A", "B", 1, 0, status="SCHEDULED")])
    assert result["available"] is False



def test_goal_markets_are_consistent_and_expose_fair_odds():
    result = predict_1x2("A", "B", sample_matches())
    assert result["available"] is True
    assert result["model_version"] == "FOOTBALL-POISSON-0.5.0"
    assert abs(result["expected_goals"]["total"] - (
        result["expected_goals"]["home"] + result["expected_goals"]["away"]
    )) < 0.01
    markets = result["goal_markets"]
    both = markets["both_teams_to_score"]
    assert 0 <= both["yes"]["probability"] <= 1
    assert 0 <= both["no"]["probability"] <= 1
    assert abs(both["yes"]["probability"] + both["no"]["probability"] - 1) < 0.01
    assert both["yes"]["fair_odds"] is not None
    assert "over_2_5" in markets["total_goals"]
    assert "home_over_1_5" in markets["team_goals"]
    assert len(result["most_likely_scorelines"]) == 5
    assert result["calibration"]["status"] == "not_calibrated"


def test_market_probabilities_are_monotonic_for_goal_thresholds():
    result = predict_1x2("A", "B", sample_matches())
    totals = result["goal_markets"]["total_goals"]
    assert totals["over_1_5"]["probability"] >= totals["over_2_5"]["probability"]
    assert totals["over_2_5"]["probability"] >= totals["over_3_5"]["probability"]
    assert totals["under_1_5"]["probability"] <= totals["under_2_5"]["probability"]
    assert totals["under_2_5"]["probability"] <= totals["under_3_5"]["probability"]

def test_official_model_excludes_results_at_or_after_target_kickoff():
    matches = sample_matches()
    for index, item in enumerate(matches, start=1):
        item["utcDate"] = f"2026-10-{index:02d}T12:00:00Z"

    future = match("A", "B", 20, 0)
    future["utcDate"] = "2026-11-01T12:00:00Z"
    same_kickoff = match("B", "A", 0, 20)
    same_kickoff["utcDate"] = "2026-10-10T12:00:00Z"
    undated = match("A", "B", 15, 0)

    result = predict_1x2(
        "A", "B",
        matches + [future, same_kickoff, undated],
        kickoff_at="2026-10-10T12:00:00+00:00",
    )

    assert result["available"] is True
    assert result["sample"]["completed_matches_in_competition"] == 9
    assert result["sample"]["excluded_at_or_after_kickoff"] == 2
    assert result["sample"]["excluded_missing_or_invalid_date"] == 1
    assert result["sample"]["pregame_cutoff_applied"] is True


def test_official_model_requires_timezone_aware_kickoff_when_cutoff_is_supplied():
    try:
        predict_1x2("A", "B", sample_matches(), kickoff_at="2026-10-10T12:00:00")
    except ValueError as exc:
        assert "zona horaria" in str(exc)
    else:
        raise AssertionError("Expected timezone-aware kickoff validation")
