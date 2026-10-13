import batter_pitcher_engine
from batter_pitcher_engine import (
    extract_confirmed_lineup,
    get_batter_pitcher_matchups,
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



def test_boxscore_fallback_finds_lineups_missing_from_pregame_feed(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "teams": {
                    "home": {
                        "battingOrder": [123],
                        "players": {
                            "ID123": {
                                "person": {"id": 123, "fullName": "Home Batter"},
                                "position": {"abbreviation": "CF"},
                            }
                        },
                    },
                    "away": {
                        "battingOrder": [456],
                        "players": {
                            "ID456": {
                                "person": {"id": 456, "fullName": "Away Batter"},
                                "position": {"abbreviation": "1B"},
                            }
                        },
                    },
                }
            }

    monkeypatch.setattr(
        batter_pitcher_engine.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(),
    )
    monkeypatch.setattr(
        batter_pitcher_engine,
        "_fetch_vs_pitcher_stats",
        lambda player_ids, pitcher_id: {},
    )

    result = get_batter_pitcher_matchups(
        feed={"liveData": {"boxscore": {"teams": {}}}},
        home_pitcher={"pitcher_id": 900, "pitcher_name": "Home Starter"},
        away_pitcher={"pitcher_id": 901, "pitcher_name": "Away Starter"},
        home_team_name="Home",
        away_team_name="Away",
        game_id=12345,
    )

    assert result["home_team"]["lineup_confirmed"] is True
    assert result["away_team"]["lineup_confirmed"] is True
    assert result["home_team"]["lineup_source"] == "game_boxscore"
    assert result["away_team"]["lineup_source"] == "game_boxscore"
    assert result["home_team"]["hitters"][0]["player_name"] == "Home Batter"
    assert result["away_team"]["hitters"][0]["player_name"] == "Away Batter"
