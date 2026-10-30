from football_h2h_experiment import EXPERIMENT_VERSION, evaluate_h2h_candidate


def match(match_id, home, away, hg, ag, date, status="FINISHED"):
    return {
        "id": match_id,
        "status": status,
        "utcDate": date,
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "score": {"fullTime": {"home": hg, "away": ag}},
    }


BASE = {"available": True, "probabilities": {"home": 0.40, "draw": 0.30, "away": 0.30}}
KICKOFF = "2026-10-25T16:00:00Z"
HISTORY = [
    match(1, "Freiburg", "Bayern", 1, 3, "2026-04-04T15:30:00Z"),
    match(2, "Bayern", "Freiburg", 6, 2, "2025-11-22T14:30:00Z"),
    match(3, "Freiburg", "Bayern", 1, 2, "2025-01-25T14:30:00Z"),
    match(4, "Bayern", "Freiburg", 2, 0, "2024-09-01T15:30:00Z"),
    match(5, "Freiburg", "Bayern", 2, 2, "2024-03-01T19:30:00Z"),
    match(6, "Bayern", "Freiburg", 3, 0, "2023-10-08T15:30:00Z"),
    match(7, "Freiburg", "Bayern", 0, 1, "2023-04-08T13:30:00Z"),
    match(8, "Bayern", "Freiburg", 5, 0, "2022-10-16T15:30:00Z"),
    match(9, "Freiburg", "Bayern", 1, 4, "2022-04-02T13:30:00Z"),
]


def test_h2h_candidate_is_shadow_only_and_probabilities_sum_to_one():
    result = evaluate_h2h_candidate("Freiburg", "Bayern", KICKOFF, BASE, HISTORY)
    assert result["available"] is True
    assert result["experiment_version"] == EXPERIMENT_VERSION
    assert result["status"] == "SHADOW_ONLY"
    assert result["h2h"]["valid_meetings"] == 9
    assert result["h2h"]["outcomes"] == {"home": 0, "draw": 1, "away": 8}
    assert abs(sum(result["candidate_probabilities"].values()) - 1.0) < 1e-9
    assert result["candidate_probabilities"]["away"] > result["base_probabilities"]["away"]
    assert result["h2h_weight"] < 0.20


def test_future_and_kickoff_time_meetings_are_excluded():
    fixtures = HISTORY + [
        match(10, "Freiburg", "Bayern", 0, 5, KICKOFF),
        match(11, "Freiburg", "Bayern", 0, 5, "2026-10-26T12:00:00Z"),
    ]
    result = evaluate_h2h_candidate("Freiburg", "Bayern", KICKOFF, BASE, fixtures)
    assert result["h2h"]["valid_meetings"] == 9
    assert result["h2h"]["excluded_at_or_after_kickoff"] == 2


def test_reversed_home_away_is_counted_from_target_fixture_perspective():
    history = [
        match(1, "Bayern", "Freiburg", 3, 1, "2025-01-01T12:00:00Z"),
        match(2, "Freiburg", "Bayern", 1, 0, "2025-02-01T12:00:00Z"),
        match(3, "Bayern", "Freiburg", 2, 2, "2025-03-01T12:00:00Z"),
    ]
    result = evaluate_h2h_candidate("Freiburg", "Bayern", KICKOFF, BASE, history)
    assert result["h2h"]["outcomes"] == {"home": 1, "draw": 1, "away": 1}


def test_duplicate_ids_are_counted_once():
    history = HISTORY[:3] + [dict(HISTORY[0])]
    result = evaluate_h2h_candidate("Freiburg", "Bayern", KICKOFF, BASE, history)
    assert result["h2h"]["valid_meetings"] == 3
    assert result["h2h"]["outcomes"] == {"home": 0, "draw": 0, "away": 3}


def test_insufficient_h2h_keeps_base_probabilities_unchanged():
    result = evaluate_h2h_candidate("Freiburg", "Bayern", KICKOFF, BASE, HISTORY[:2])
    assert result["status"] == "INSUFFICIENT_H2H"
    assert result["candidate_probabilities"] == result["base_probabilities"]
    assert result["h2h_weight"] == 0.0


def test_invalid_base_prediction_returns_unavailable():
    result = evaluate_h2h_candidate("Freiburg", "Bayern", KICKOFF, {"available": True, "probabilities": {}}, HISTORY)
    assert result["available"] is False


def test_invalid_inputs_are_rejected():
    try:
        evaluate_h2h_candidate("Freiburg", "Freiburg", KICKOFF, BASE, HISTORY)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")
