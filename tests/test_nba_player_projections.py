from nba_player_projections import aggregate_player_projections


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
    assert player["games_sampled_by_stat"]["points"] == 1
    assert home["statistical_coverage"]["points"] == 1


def test_empty_or_unavailable_boxscores_return_no_fabricated_projections():
    result = aggregate_player_projections({}, {"1": []})
    assert result["available"] is False
    assert result["teams"] == []
    assert result["player_count"] == 0
