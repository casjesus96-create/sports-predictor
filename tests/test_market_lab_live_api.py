from fastapi import HTTPException

from market_lab_api import get_live_mlb_batter_report


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "gameData": {
                "status": {"abstractGameState": "Live", "detailedState": "In Progress"},
                "teams": {
                    "away": {"id": 1, "name": "Away Team"},
                    "home": {"id": 2, "name": "Home Team"},
                },
            },
            "liveData": {
                "linescore": {
                    "teams": {"away": {"runs": 2}, "home": {"runs": 1}},
                    "currentInning": 4,
                    "inningState": "Top",
                    "outs": 1,
                },
                "boxscore": {
                    "teams": {
                        "away": {
                            "battingOrder": [123],
                            "players": {
                                "ID123": {
                                    "person": {"id": 123, "fullName": "Test Hitter"},
                                    "position": {"abbreviation": "CF"},
                                    "stats": {"batting": {"hits": 1, "atBats": 2}},
                                }
                            },
                        },
                        "home": {"battingOrder": [], "players": {}},
                    }
                },
            },
        }


def test_live_batter_report_returns_observed_boxscore_only(monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse())
    result = get_live_mlb_batter_report("12345")

    assert result["success"] is True
    assert result["game_status"] == "Live"
    assert result["away_score"] == 2
    assert result["home_score"] == 1
    assert result["probabilities_available"] is False
    hitter = result["teams"][0]["hitters"][0]
    assert hitter["player_name"] == "Test Hitter"
    assert hitter["hits_in_game"] == 1
    assert hitter["at_bats_in_game"] == 2
    assert hitter["game_avg"] == 0.5


def test_live_batter_report_rejects_non_numeric_game_id():
    try:
        get_live_mlb_batter_report("not-a-game-id")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected HTTP 400 for non-numeric game ID")
