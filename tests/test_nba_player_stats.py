from nba_player_stats import parse_player_boxscore


def test_parse_player_boxscore_maps_requested_stats_and_skips_dnp():
    payload = {
        "boxscore": {
            "players": [
                {
                    "team": {"id": "1", "displayName": "Home Team", "abbreviation": "HOM"},
                    "statistics": [{
                        "names": ["MIN", "REB", "AST", "STL", "BLK", "PTS"],
                        "athletes": [
                            {"athlete": {"id": "10", "displayName": "Player One", "position": {"abbreviation": "G"}},
                             "starter": True, "stats": ["30", "8", "7", "2", "1", "24"]},
                            {"athlete": {"id": "11", "displayName": "Player Two"},
                             "didNotPlay": True, "stats": ["0", "0", "0", "0", "0", "0"]},
                        ],
                    }],
                }
            ]
        }
    }
    report = parse_player_boxscore(payload, "123")
    assert report["available"] is True
    assert report["player_count"] == 1
    player = report["teams"][0]["players"][0]
    assert player["points"] == 24
    assert player["assists"] == 7
    assert player["rebounds"] == 8
    assert player["blocks"] == 1
    assert player["steals"] == 2


def test_parse_player_boxscore_handles_missing_stats_without_fabricating_values():
    report = parse_player_boxscore({"boxscore": {"players": []}}, "456")
    assert report["available"] is False
    assert report["player_count"] == 0
    assert report["teams"] == []
