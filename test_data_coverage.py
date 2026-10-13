from data_coverage import calculate_data_coverage


def coverage(**overrides):
    values = {
        "home_hitting": {"ops": 0.0},
        "away_hitting": {"ops": 0.7},
        "home_pitching": {"era": 0.0},
        "away_pitching": {"era": 4.2},
        "home_pitcher_id": 101,
        "away_pitcher_id": 202,
        "home_pitcher_stats": {"era": 0.0},
        "away_pitcher_stats": {"inningsPitched": "10.0"},
        "home_form": {"last_15": {"games": 15}},
        "away_form": {"last_15": {"games": 15}},
    }
    values.update(overrides)
    return calculate_data_coverage(**values)


def test_complete_data_has_full_coverage_and_zero_is_valid():
    result = coverage()
    assert result["score"] == 100
    assert isinstance(result["score"], int)
    assert result["complete"] is True
    assert result["missing_fields"] == []
    assert result["components"]["home_team_ops"]["available"] is True
    assert result["components"]["home_team_era"]["available"] is True


def test_missing_stats_reduce_score_and_are_reported():
    result = coverage(
        home_hitting={},
        away_pitching={},
        away_pitcher_id=None,
        away_pitcher_stats={},
    )
    assert result["score"] < 100
    assert "home_team_ops" in result["missing_fields"]
    assert "away_team_era" in result["missing_fields"]
    assert "away_starter_stats" in result["missing_fields"]
    assert result["complete"] is False


def test_recent_form_coverage_is_proportional_to_sample_size():
    result = coverage(
        home_form={"last_15": {"games": 5}},
        away_form={"last_15": {"games": 10}},
    )
    home = result["components"]["home_recent_form"]
    away = result["components"]["away_recent_form"]
    assert home["coverage"] == 5 / 15
    assert away["coverage"] == 10 / 15
    assert result["score"] < 100
    assert result["complete"] is False


def test_invalid_or_non_finite_values_are_not_available():
    result = coverage(
        home_hitting={"ops": "unknown"},
        away_pitching={"era": float("nan")},
    )
    assert result["components"]["home_team_ops"]["available"] is False
    assert result["components"]["away_team_era"]["available"] is False
