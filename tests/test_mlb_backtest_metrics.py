from mlb_backtest import calculate_mlb_backtest_metrics


def _snapshot(event_id, cutoff, home_expected, away_expected):
    return {
        "event_id": event_id,
        "model_version": "2.0.0-matchup",
        "result_status": "SETTLED",
        "created_at": cutoff,
        "data_cutoff": cutoff,
        "features": {
            "game": {"date": "2026-06-10T19:00:00Z"},
            "factors": {
                "run_projection": {
                    "available": True,
                    "home": {"expected_runs": home_expected},
                    "away": {"expected_runs": away_expected},
                    "probability_tied_after_nine": 0.2,
                }
            },
        },
        "actual_home_score": 4,
        "actual_away_score": 3,
    }


def test_run_backtest_counts_one_snapshot_per_event_and_uses_newest_valid():
    older = _snapshot("game-1", "2026-06-10T17:00:00Z", 2.0, 2.0)
    newer = _snapshot("game-1", "2026-06-10T18:00:00Z", 4.0, 3.0)

    result = calculate_mlb_backtest_metrics([older, newer], {"game-1": False})

    assert result["sample_size"] == 1
    assert result["team_run_observations"] == 2
    assert result["run_metrics"]["home_runs"]["mae"] == 0.0
    assert result["run_metrics"]["away_runs"]["mae"] == 0.0
    assert result["tie_after_nine"]["sample_size"] == 1
    assert result["exclusions"]["duplicate_event"] == 1


def test_run_backtest_does_not_let_invalid_newer_snapshot_hide_valid_older():
    older = _snapshot("game-2", "2026-06-10T17:00:00Z", 4.0, 3.0)
    newer = _snapshot("game-2", "2026-06-10T18:00:00Z", -1.0, 3.0)

    result = calculate_mlb_backtest_metrics([older, newer])

    assert result["sample_size"] == 1
    assert result["run_metrics"]["home_runs"]["mae"] == 0.0
    assert result["exclusions"]["missing_or_invalid_run_projection"] == 1
