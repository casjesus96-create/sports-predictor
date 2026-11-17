from mlb_backtest import calculate_pitcher_strikeout_accuracy


def _row(event_id, home_pred=6.0, away_pred=5.0, home_actual=7, away_actual=4):
    return {
        "event_id": str(event_id),
        "model_version": "2.0.0-matchup",
        "result_status": "SETTLED",
        "data_cutoff": "2026-06-01T15:00:00+00:00",
        "features": {
            "game": {"date": "2026-06-01T19:00:00+00:00"},
            "factors": {
                "probable_pitchers": {
                    "home": {"pitcher_id": "101"},
                    "away": {"pitcher_id": "202"},
                },
                "pitcher_strikeout_projection": {
                    "home_pitcher": {"available": True, "expected_strikeouts": home_pred},
                    "away_pitcher": {"available": True, "expected_strikeouts": away_pred},
                },
            },
            "actual_pitcher_strikeout_observations": {
                "observations": {
                    "home": {"status": "matched", "pitcher_id": "101", "strikeouts": home_actual},
                    "away": {"status": "matched", "pitcher_id": "202", "strikeouts": away_actual},
                }
            },
        },
    }


def test_calculates_overall_and_home_away_error_metrics():
    result = calculate_pitcher_strikeout_accuracy([_row("1")])
    assert result["overall"]["sample_size"] == 2
    assert result["overall"]["mae"] == 1.0
    assert result["overall"]["rmse"] == 1.0
    assert result["overall"]["bias"] == 0.0
    assert result["home_pitcher"]["bias"] == -1.0
    assert result["away_pitcher"]["bias"] == 1.0


def test_excludes_unverified_actual_and_pitcher_identity_mismatch():
    row = _row("1")
    row["features"]["factors"]["probable_pitchers"]["home"]["pitcher_id"] = "999"
    row["features"]["actual_pitcher_strikeout_observations"]["observations"]["away"]["status"] = "starter_mismatch"
    result = calculate_pitcher_strikeout_accuracy([row])
    assert result["overall"]["sample_size"] == 0
    assert result["exclusions"]["pitcher_identity_mismatch"] == 1
    assert result["exclusions"]["missing_or_unverified_actual"] == 1


def test_excludes_invalid_projection_and_non_pregame_snapshot():
    row = _row("1", home_pred=float("nan"))
    row["features"]["factors"]["pitcher_strikeout_projection"]["away_pitcher"]["expected_strikeouts"] = -1
    result = calculate_pitcher_strikeout_accuracy([row])
    assert result["overall"]["sample_size"] == 0
    assert result["exclusions"]["missing_or_invalid_projection"] == 2

    row = _row("2")
    row["data_cutoff"] = "2026-06-01T20:00:00+00:00"
    result = calculate_pitcher_strikeout_accuracy([row])
    assert result["overall"]["sample_size"] == 0
    assert result["exclusions"]["not_official_settled_pregame_snapshot"] == 1


def test_counts_each_event_once():
    result = calculate_pitcher_strikeout_accuracy([_row("1"), _row("1")])
    assert result["overall"]["sample_size"] == 2
    assert result["exclusions"]["duplicate_event"] == 1


def test_empty_sample_returns_null_metrics_not_zero_accuracy():
    result = calculate_pitcher_strikeout_accuracy([])
    assert result["overall"]["sample_size"] == 0
    assert result["overall"]["mae"] is None
    assert result["overall"]["bias"] is None
