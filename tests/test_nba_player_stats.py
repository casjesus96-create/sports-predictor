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



def test_parse_player_boxscore_includes_quarter_scores_and_overtime():
    payload = {
        "header": {"competitions": [{
            "competitors": [
                {"homeAway": "away", "score": "111", "linescores": [
                    {"period": 1, "displayValue": "25"}, {"period": 2, "displayValue": "30"},
                    {"period": 3, "displayValue": "28"}, {"period": 4, "displayValue": "20"},
                    {"period": 5, "displayValue": "8"},
                ]},
                {"homeAway": "home", "score": "114", "linescores": [
                    {"period": 1, "displayValue": "27"}, {"period": 2, "displayValue": "25"},
                    {"period": 3, "displayValue": "31"}, {"period": 4, "displayValue": "20"},
                    {"period": 5, "displayValue": "11"},
                ]},
            ]
        }]},
        "boxscore": {"players": []},
    }
    report = parse_player_boxscore(payload, "789")
    quarter_scores = report["quarter_scores"]
    assert quarter_scores["available"] is True
    assert [period["label"] for period in quarter_scores["periods"]] == ["Q1", "Q2", "Q3", "Q4", "OT1"]
    assert quarter_scores["periods"][0]["away_points"] == 25
    assert quarter_scores["periods"][4]["home_points"] == 11
    assert quarter_scores["away_total"] == 111
    assert quarter_scores["home_total"] == 114


def test_parse_player_boxscore_quarter_scores_are_unavailable_when_missing():
    report = parse_player_boxscore({"boxscore": {"players": []}}, "790")
    assert report["quarter_scores"]["available"] is False
    assert report["quarter_scores"]["periods"] == []
    assert report["quarter_scores"]["away_total"] is None
    assert report["quarter_scores"]["home_total"] is None
