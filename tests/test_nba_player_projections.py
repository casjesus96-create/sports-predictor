from nba_player_projections import aggregate_player_projections
from nba_player_stats import parse_player_boxscore


def test_aggregates_player_stats_by_appearances_and_team():
    histories = {
        "1": [{"game_id": "g1", "home_team_id": "1", "home": "Home", "kickoff": "2026-10-01T00:00:00Z"}],
        "2": [{"game_id": "g1", "away_team_id": "2", "away": "Away", "kickoff": "2026-10-01T00:00:00Z"}],
    }
    reports = {
        "g1": {
            "available": True,
            "teams": [
                {"team_id": "1", "team": "Home", "players": [
                    {"player_id": "10", "name": "Player One", "points": 20, "assists": 5, "rebounds": 7, "blocks": 1, "steals": 2}
                ]},
                {"team_id": "2", "team": "Away", "players": [
                    {"player_id": "20", "name": "Player Two", "points": 12, "assists": 8, "rebounds": 4, "blocks": 0, "steals": 1}
                ]},
            ],
        }
    }
    result = aggregate_player_projections(reports, histories)
    assert result["available"] is True
    home = next(team for team in result["teams"] if team["team_id"] == "1")
    player = home["players"][0]
    assert player["projected_points"] == 20
    assert player["projected_assists"] == 5
    assert player["projected_rebounds"] == 7
    assert player["projected_blocks"] == 1
    assert player["projected_steals"] == 2
    assert player["games_sampled"] == 1


def test_empty_or_unavailable_boxscores_return_no_fabricated_projections():
    result = aggregate_player_projections({}, {"1": []})
    assert result["available"] is False
    assert result["teams"] == []
    assert result["player_count"] == 0


def test_parser_handles_espn_labels_and_derives_points_from_made_shots():
    payload = {
        "boxscore": {
            "players": [
                {
                    "team": {"id": "1", "displayName": "Cleveland Cavaliers", "abbreviation": "CLE"},
                    "statistics": [
                        {
                            "labels": ["MIN", "FG", "3PT", "FT", "REB", "AST", "STL", "BLK"],
                            "athletes": [
                                {
                                    "athlete": {"id": "10", "displayName": "Example Player", "position": {"abbreviation": "G"}},
                                    "starter": True,
                                    "stats": ["32:10", "9-18", "3-7", "4-4", "6", "5", "2", "1"],
                                },
                                {
                                    "athlete": {"id": "11", "displayName": "Did Not Play"},
                                    "didNotPlay": True,
                                    "stats": ["DNP", "-", "-", "-", "-", "-", "-", "-"],
                                },
                            ],
                        }
                    ],
                }
            ]
        }
    }
    result = parse_player_boxscore(payload, "123")
    assert result["available"] is True
    assert result["player_count"] == 1
    player = result["teams"][0]["players"][0]
    assert player["name"] == "Example Player"
    assert player["points"] == 25  # 2*9 field goals + 3 made threes + 4 free throws
    assert player["rebounds"] == 6
    assert player["assists"] == 5
    assert player["steals"] == 2
    assert player["blocks"] == 1


def test_parser_does_not_invent_points_when_shooting_data_is_incomplete():
    payload = {
        "boxscore": {
            "players": [
                {
                    "team": {"id": "2", "displayName": "Philadelphia 76ers"},
                    "statistics": [
                        {
                            "names": ["REB", "AST", "STL", "BLK", "FG", "FT"],
                            "athletes": [
                                {"athlete": {"id": "20", "displayName": "Example"}, "stats": ["4", "3", "1", "0", "5-10", "2-2"]}
                            ],
                        }
                    ],
                }
            ]
        }
    }
    player = parse_player_boxscore(payload, "456")["teams"][0]["players"][0]
    assert player["points"] is None
    assert player["rebounds"] == 4
