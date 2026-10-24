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
