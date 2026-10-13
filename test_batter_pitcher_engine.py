from batter_pitcher_engine import normalize_batter_pitcher_stats


def test_missing_batter_pitcher_history_is_not_invented():
    result = normalize_batter_pitcher_stats([])
    assert result["available"] is False
    assert result["avg"] is None
    assert result["slg"] is None
    assert result["ops"] is None
