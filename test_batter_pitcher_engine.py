from batter_pitcher_engine import (
    extract_confirmed_lineup,
    normalize_batter_pitcher_stats,
)


def test_missing_batter_pitcher_history_is_not_invented():
    result = normalize_batter_pitcher_stats([])
    assert result["available"] is False
    assert result["sample_size"] == 0
    assert result["avg"] is None
    assert result["slg"] is None
    assert result["ops"] is None


def test_direct_batter_pitcher_rates_are_calculated_from_counts():
    result = normalize_batter_pitcher_stats([
        {
            "stat": {
                "plateAppearances": 13,
                "atBats": 10,
                "hits": 3,
                "homeRuns": 1,
                "doubles": 1,
                "triples": 0,
                "baseOnBalls": 2,
                "hitByPitch": 0,
                "sacFlies": 1,
            }
        }
    ])
    assert result["available"] is True
    assert result["sample_size"] == 13
    assert result["avg"] == 0.3
    assert result["slg"] == 0.7
    assert result["ops"] == 1.085
    assert result["home_runs"] == 1


def test_only_batters_in_published_order_are_returned():
    feed = {
        "liveData": {
            "boxscore": {
                "teams": {
                    "home": {
                        "battingOrder": [123, 456],
                        "players": {
                            "ID123": {
                                "person": {"id": 123, "fullName": "Batter One"},
                                "position": {"abbreviation": "CF"},
                            },
                            "ID456": {
                                "person": {"id": 456, "fullName": "Batter Two"},
                                "position": {"abbreviation": "1B"},
                            },
                            "ID789": {
                                "person": {"id": 789, "fullName": "Bench Player"},
                                "position": {"abbreviation": "C"},
                            },
                        },
                    }
                }
            }
        }
    }
    lineup = extract_confirmed_lineup(feed, "home")
    assert [hitter["player_id"] for hitter in lineup] == [123, 456]
    assert [hitter["batting_order"] for hitter in lineup] == [1, 2]
    assert lineup[0]["player_name"] == "Batter One"


def test_unpublished_lineup_returns_empty_list():
    feed = {"liveData": {"boxscore": {"teams": {}}}}
    assert extract_confirmed_lineup(feed, "home") == []
