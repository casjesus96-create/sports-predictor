from mlb_backtest import extract_pitcher_strikeout_observations


def _feed(*, final=True, home_pitcher_id=101, away_pitcher_id=202,
          home_ks=7, away_ks=4):
    return {
        "gameData": {"status": {"abstractGameState": "Final" if final else "Live"}},
        "liveData": {
            "boxscore": {
                "teams": {
                    "home": {
                        "pitchers": [home_pitcher_id, 103],
                        "players": {
                            f"ID{home_pitcher_id}": {
                                "stats": {"pitching": {"strikeOuts": home_ks}}
                            }
                        },
                    },
                    "away": {
                        "pitchers": [away_pitcher_id, 204],
                        "players": {
                            f"ID{away_pitcher_id}": {
                                "stats": {"pitching": {"strikeOuts": away_ks}}
                            }
                        },
                    },
                }
            }
        },
    }


def _features(home_id=101, away_id=202):
    return {
        "factors": {
            "probable_pitchers": {
                "home": {"pitcher_id": home_id},
                "away": {"pitcher_id": away_id},
            }
        }
    }


def test_extracts_strikeouts_only_for_matching_saved_starting_pitchers():
    result = extract_pitcher_strikeout_observations(_feed(), _features())
    assert result["status"] == "captured"
    assert result["observations"]["home"] == {
        "status": "matched", "pitcher_id": "101", "strikeouts": 7
    }
    assert result["observations"]["away"] == {
        "status": "matched", "pitcher_id": "202", "strikeouts": 4
    }


def test_does_not_assign_another_pitchers_strikeouts_to_saved_projection():
    result = extract_pitcher_strikeout_observations(
        _feed(home_pitcher_id=999), _features()
    )
    assert result["status"] == "captured"
    assert result["observations"]["home"]["status"] == "starter_mismatch"
    assert "strikeouts" not in result["observations"]["home"]
    assert result["observations"]["away"]["strikeouts"] == 4


def test_rejects_non_final_game_feed():
    result = extract_pitcher_strikeout_observations(
        _feed(final=False), _features()
    )
    assert result["status"] == "game_not_final"


def test_missing_or_non_integer_strikeouts_are_not_recorded():
    result = extract_pitcher_strikeout_observations(
        _feed(home_ks=None, away_ks=4.5), _features()
    )
    assert result["status"] == "no_verified_starter_observations"
    assert result["observations"]["home"]["status"] == "missing_or_invalid_boxscore_strikeouts"
    assert result["observations"]["away"]["status"] == "missing_or_invalid_boxscore_strikeouts"


def test_missing_pregame_pitcher_identity_is_excluded():
    result = extract_pitcher_strikeout_observations(_feed(), _features(home_id=None))
    assert result["observations"]["home"]["status"] == "missing_pitcher_identity"
    assert "strikeouts" not in result["observations"]["home"]
