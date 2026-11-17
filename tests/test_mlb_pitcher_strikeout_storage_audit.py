from mlb_backtest import diagnose_pitcher_strikeout_storage


def _row(projection=None, home_pitcher_id=101, away_pitcher_id=202):
    return {
        "result_status": "SETTLED",
        "model_version": "2.0.0-matchup",
        "created_at": "2026-06-01T12:00:00+00:00",
        "data_cutoff": "2026-06-01T11:00:00+00:00",
        "features": {
            "game": {"date": "2026-06-01T19:00:00+00:00"},
            "factors": {
                "probable_pitchers": {
                    "home": {"pitcher_id": home_pitcher_id},
                    "away": {"pitcher_id": away_pitcher_id},
                },
                "pitcher_strikeout_projection": projection or {},
            },
        },
    }


def test_reports_valid_home_and_away_strikeout_projection_coverage():
    row = _row({
        "home_pitcher": {"available": True, "expected_strikeouts": 6.4},
        "away_pitcher": {"available": True, "expected_strikeouts": 4.8},
    })
    result = diagnose_pitcher_strikeout_storage([row])
    assert result["official_settled_pregame_snapshots"] == 1
    assert result["snapshots_with_projection"] == 1
    assert result["home_pitcher_projection_count"] == 1
    assert result["away_pitcher_projection_count"] == 1
    assert result["home_pitcher_id_present"] == 1
    assert result["away_pitcher_id_present"] == 1


def test_missing_or_invalid_strikeout_projection_is_not_counted_as_zero():
    row = _row({
        "home_pitcher": {"available": True, "expected_strikeouts": float("nan")},
        "away_pitcher": {"available": False, "expected_strikeouts": None},
    })
    result = diagnose_pitcher_strikeout_storage([row])
    assert result["snapshots_with_projection"] == 0
    assert result["missing_or_invalid_projection_count"] == 1
    assert result["home_pitcher_projection_count"] == 0
    assert result["away_pitcher_projection_count"] == 0


def test_actual_pitcher_strikeout_accuracy_is_explicitly_not_evaluable():
    result = diagnose_pitcher_strikeout_storage([_row()])
    assert result["actual_strikeouts_available_in_snapshot"] == 0
    assert result["evaluation_status"] == "not_evaluable_actual_pitcher_strikeouts_not_stored"


def test_non_pregame_snapshot_is_not_counted_as_eligible():
    row = _row({"home_pitcher": {"available": True, "expected_strikeouts": 5}})
    row["data_cutoff"] = "2026-06-01T20:00:00+00:00"
    result = diagnose_pitcher_strikeout_storage([row])
    assert result["official_settled_pregame_snapshots"] == 0
