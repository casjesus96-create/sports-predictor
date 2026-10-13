from mlb_backtest import (
    actual_tie_after_nine,
    calculate_mlb_backtest_metrics,
    snapshot_pregame_eligible,
)


def snapshot(event_id="101", cutoff="2026-06-01T12:00:00Z", start="2026-06-01T17:00:00Z",
             home_expected=4.2, away_expected=3.8, tie_probability=0.18,
             home_actual=5, away_actual=3, model="2.0.0-matchup", status="SETTLED"):
    return {
        "event_id": event_id,
        "model_version": model,
        "result_status": status,
        "created_at": cutoff,
        "data_cutoff": cutoff,
        "actual_home_score": home_actual,
        "actual_away_score": away_actual,
        "features": {
            "game": {"date": start},
            "factors": {
                "run_projection": {
                    "available": True,
                    "home": {"expected_runs": home_expected},
                    "away": {"expected_runs": away_expected},
                    "probability_tied_after_nine": tie_probability,
                }
            },
        },
    }


def test_only_settled_official_snapshots_with_pregame_cutoff_are_eligible():
    assert snapshot_pregame_eligible(snapshot())
    assert not snapshot_pregame_eligible(snapshot(cutoff="2026-06-01T17:00:00Z"))
    assert not snapshot_pregame_eligible(snapshot(model="old-model"))
    assert not snapshot_pregame_eligible(snapshot(status="PENDING"))


def test_run_errors_and_tie_brier_are_calculated_from_eligible_rows():
    rows = [
        snapshot(event_id="101", home_expected=4, away_expected=4, tie_probability=0.25,
                 home_actual=5, away_actual=3),
        snapshot(event_id="102", home_expected=6, away_expected=2, tie_probability=0.75,
                 home_actual=4, away_actual=2),
        snapshot(event_id="103", model="legacy"),
    ]
    result = calculate_mlb_backtest_metrics(rows, {"101": False, "102": True})
    assert result["sample_size"] == 2
    assert result["run_metrics"]["home_runs"]["mae"] == 1.5
    assert result["run_metrics"]["away_runs"]["mae"] == 0.5
    assert result["run_metrics"]["per_team"]["mae"] == 1.0
    assert result["tie_after_nine"]["sample_size"] == 2
    assert result["tie_after_nine"]["brier_score"] == 0.0625
    assert result["exclusions"]["not_official_settled_pregame_snapshot"] == 1


def test_missing_projection_or_score_is_excluded_not_fabricated():
    missing_projection = snapshot(event_id="201")
    missing_projection["features"]["factors"]["run_projection"]["available"] = False
    missing_score = snapshot(event_id="202", home_actual=None)
    result = calculate_mlb_backtest_metrics([missing_projection, missing_score])
    assert result["sample_size"] == 0
    assert result["exclusions"]["missing_or_invalid_run_projection"] == 1
    assert result["exclusions"]["missing_or_invalid_final_score"] == 1
    assert result["run_metrics"]["per_team"]["mae"] is None
    assert result["tie_after_nine"]["brier_score"] is None


def test_tie_observation_uses_first_nine_innings_only():
    innings = []
    for index in range(10):
        innings.append({
            "home": {"runs": 1 if index == 0 else 0},
            "away": {"runs": 1 if index == 0 else 0},
        })
    feed = {
        "gameData": {"status": {"abstractGameState": "Final"}},
        "liveData": {"linescore": {"scheduledInnings": 9, "innings": innings}},
    }
    assert actual_tie_after_nine(feed) is True
    innings[8]["home"]["runs"] = 1
    assert actual_tie_after_nine(feed) is False


def test_tie_observation_skips_live_shortened_and_incomplete_games():
    assert actual_tie_after_nine({
        "gameData": {"status": {"abstractGameState": "Live"}},
        "liveData": {"linescore": {"scheduledInnings": 9, "innings": []}},
    }) is None
    assert actual_tie_after_nine({
        "gameData": {"status": {"abstractGameState": "Final"}},
        "liveData": {"linescore": {"scheduledInnings": 7, "innings": []}},
    }) is None
    assert actual_tie_after_nine({
        "gameData": {"status": {"abstractGameState": "Final"}},
        "liveData": {"linescore": {"scheduledInnings": 9, "innings": []}},
    }) is None
