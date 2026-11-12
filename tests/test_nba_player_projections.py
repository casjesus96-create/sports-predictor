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
    assert player["recent_windows"]["points"]["5"]["average"] == 20
    assert player["recent_windows"]["points"]["10"]["games"] == 1
    assert player["recent_windows"]["points"]["15"]["median"] == 20
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

def test_projection_coverage_excludes_opponents_from_historical_boxscores():
    histories = {
        "home-id": [{
            "game_id": "old-game",
            "home_team_id": "home-id",
            "home": "Home Team",
            "kickoff": "2026-10-01T00:00:00Z",
        }],
        "away-id": [{
            "game_id": "old-game",
            "away_team_id": "away-id",
            "away": "Away Team",
            "kickoff": "2026-10-01T00:00:00Z",
        }],
    }
    reports = {
        "old-game": {
            "available": True,
            "teams": [
                {"team_id": "home-id", "team": "Home Team", "players": [
                    {"player_id": "h1", "name": "Home Player", "points": 20}
                ]},
                {"team_id": "away-id", "team": "Away Team", "players": [
                    {"player_id": "a1", "name": "Away Player", "points": 10}
                ]},
                {"team_id": "opponent-id", "team": "Unrelated Opponent", "players": [
                    {"player_id": "x1", "name": "Opponent Player", "points": 99}
                ]},
            ],
        }
    }

    result = aggregate_player_projections(reports, histories)

    assert {team["team_id"] for team in result["teams"]} == {"home-id", "away-id"}
    assert result["player_count"] == 2
    assert all(team["team"] != "Equipo" for team in result["teams"])
    home = next(team for team in result["teams"] if team["team_id"] == "home-id")
    assert home["statistical_coverage"]["points"] == 1
    assert home["players"][0]["projected_points"] == 20



def test_project_players_fetches_up_to_fifteen_most_recent_pregame_games(monkeypatch):
    import nba_player_projections as module

    histories = {
        "1": [
            {
                "game_id": f"g{index}",
                "kickoff": f"2026-10-{index:02d}T00:00:00Z",
                "completed": True,
                "home_team_id": "1",
                "home": "Home",
            }
            for index in range(1, 17)
        ]
    }
    fetched = []

    def fake_fetch(game_id):
        fetched.append(game_id)
        return {
            "available": True,
            "teams": [{
                "team_id": "1",
                "players": [{
                    "player_id": "p1",
                    "name": "Player One",
                    "points": float(int(game_id[1:])),
                    "assists": 2,
                    "rebounds": 3,
                    "blocks": 1,
                    "steals": 0,
                }],
            }],
        }

    monkeypatch.setattr(module, "fetch_player_boxscore", fake_fetch)
    result = module.project_players_from_recent_games(
        histories, "2026-10-20T00:00:00Z"
    )

    assert len(fetched) == 15
    assert set(fetched) == {f"g{index}" for index in range(2, 17)}
    player = result["teams"][0]["players"][0]
    assert player["recent_windows"]["points"]["5"]["games"] == 5
    assert player["recent_windows"]["points"]["10"]["games"] == 10
    assert player["recent_windows"]["points"]["15"]["games"] == 15
    assert player["recent_windows"]["points"]["5"]["average"] != player["recent_windows"]["points"]["15"]["average"]


def test_player_market_history_preserves_raw_pregame_boxscore_records():
    histories = {
        "1": [
            {"game_id": "g1", "home_team_id": "1", "home": "Home", "kickoff": "2026-10-01T00:00:00Z", "completed": True},
            {"game_id": "g2", "home_team_id": "1", "home": "Home", "kickoff": "2026-10-02T00:00:00Z", "completed": True},
        ]
    }
    reports = {
        "g1": {"available": True, "teams": [{"team_id": "1", "players": [
            {"player_id": "p1", "name": "Player", "points": 10, "rebounds": 4, "assists": 3}
        ]}]},
        "g2": {"available": True, "teams": [{"team_id": "1", "players": [
            {"player_id": "p1", "name": "Player", "points": 20, "rebounds": 5, "assists": 6}
        ]}]},
    }
    result = aggregate_player_projections(reports, histories)
    player = result["teams"][0]["players"][0]
    assert [row["game_id"] for row in player["market_history"]] == ["g2", "g1"]
    assert player["market_history"][0]["completed"] is True
    assert player["market_history"][0]["points"] == 20
    assert player["market_history"][0]["rebounds"] == 5
    assert player["market_history"][0]["assists"] == 6
