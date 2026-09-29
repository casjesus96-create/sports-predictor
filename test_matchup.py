import os

from matchup_engine import calculate_h2h, get_matchup_data


HOME_TEAM_ID = 147  # New York Yankees
AWAY_TEAM_ID = 139  # Tampa Bay Rays
BEFORE_DATE = "2026-09-22T00:00:00Z"


def test_h2h_shape():
    result = calculate_h2h(
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        before_date=BEFORE_DATE,
        limit=10,
    )

    assert isinstance(result, dict)
    assert "available" in result
    assert "games" in result
    assert "home_team_wins" in result
    assert "away_team_wins" in result
    assert "home_team_runs" in result
    assert "away_team_runs" in result
    assert "home_team_run_differential" in result
    assert isinstance(result["games"], int)


def test_matchup_shape():
    result = get_matchup_data(
        game_id=0,
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        before_date=BEFORE_DATE,
        season=2026,
        game_type="R",
    )

    assert result["available"] is True
    assert result["home_team_id"] == HOME_TEAM_ID
    assert result["away_team_id"] == AWAY_TEAM_ID
    assert "pitchers" in result
    assert "pitcher_hands" in result
    assert "h2h" in result
    assert "general_context" in result
    assert "batting_splits" in result
    assert "bullpen" in result


def test_only_official_model_is_declared():
    from prediction import MODEL_VERSION

    assert MODEL_VERSION == "2.0.0-matchup"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))
