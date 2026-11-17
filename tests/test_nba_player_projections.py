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



def test_project_players_fetches_twenty_pregame_games_for_market_backtesting(monkeypatch):
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
            for index in range(1, 23)
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
        histories, "2026-10-30T00:00:00Z"
    )

    assert len(fetched) == 20
    assert set(fetched) == {f"g{index}" for index in range(3, 23)}
    player = result["teams"][0]["players"][0]
    assert result["max_games_per_team"] == 20
    assert len(player["market_history"]) == 20
    assert player["recent_windows"]["points"]["5"]["games"] == 5
    assert player["recent_windows"]["points"]["10"]["games"] == 10
    assert player["recent_windows"]["points"]["15"]["games"] == 15
    assert player["recent_windows"]["points"]["5"]["average"] == 20
    assert player["projected_points"] == 20


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


def test_invalid_boxscore_stats_are_excluded_from_projection_and_market_history():
    histories = {
        "1": [{"game_id": "g1", "home_team_id": "1", "home": "Home", "kickoff": "2026-10-01T00:00:00Z"}],
    }
    reports = {
        "g1": {
            "available": True,
            "teams": [{"team_id": "1", "players": [{
                "player_id": "p1", "name": "Player",
                "points": 18,
                "assists": float("nan"),
                "rebounds": -2,
                "blocks": float("inf"),
                "steals": True,
            }]}],
        }
    }

    result = aggregate_player_projections(reports, histories)

    player = result["teams"][0]["players"][0]
    assert player["projected_points"] == 18
    assert player["projected_assists"] is None
    assert player["projected_rebounds"] is None
    assert player["projected_blocks"] is None
    assert player["projected_steals"] is None
    assert player["games_sampled_by_stat"] == {
        "points": 1, "assists": 0, "rebounds": 0, "blocks": 0, "steals": 0,
    }
    assert player["market_history"] == [{
        "game_id": "g1", "kickoff": "2026-10-01T00:00:00+00:00",
        "completed": True, "points": 18.0,
    }]



def test_projection_ignores_unrequested_boxscores_and_deduplicates_player_game_stats():
    histories = {
        "1": [{"game_id": "requested", "home_team_id": "1", "home": "Home", "kickoff": "2026-10-01T00:00:00Z"}],
    }
    reports = {
        "requested": {
            "available": True,
            "teams": [{"team_id": "1", "players": [
                {"player_id": "p1", "name": "Player", "points": 20, "assists": 4},
                {"player_id": "p1", "name": "Player", "points": 20, "assists": 4},
            ]}],
        },
        "unrequested": {
            "available": True,
            "teams": [{"team_id": "1", "players": [
                {"player_id": "p1", "name": "Player", "points": 100, "assists": 20},
            ]}],
        },
    }

    result = aggregate_player_projections(reports, histories)
    player = result["teams"][0]["players"][0]

    assert player["projected_points"] == 20
    assert player["projected_assists"] == 4
    assert player["games_sampled"] == 1
    assert player["games_sampled_by_stat"]["points"] == 1
    assert player["duplicate_stat_records_excluded"] == 2
    assert [row["game_id"] for row in player["market_history"]] == ["requested"]


def test_conflicting_duplicate_player_stat_for_same_game_is_excluded():
    histories = {
        "1": [{"game_id": "g1", "home_team_id": "1", "home": "Home", "kickoff": "2026-10-01T00:00:00Z"}],
    }
    reports = {
        "g1": {
            "available": True,
            "teams": [{"team_id": "1", "players": [
                {"player_id": "p1", "name": "Player", "points": 20, "assists": 4},
                {"player_id": "p1", "name": "Player", "points": 22, "assists": 4},
            ]}],
        }
    }

    result = aggregate_player_projections(reports, histories)
    player = result["teams"][0]["players"][0]

    assert player["projected_points"] is None
    assert player["games_sampled_by_stat"]["points"] == 0
    assert player["projected_assists"] == 4
    assert player["market_history"] == [{
        "game_id": "g1", "kickoff": "2026-10-01T00:00:00+00:00",
        "completed": True, "assists": 4.0,
    }]
    assert player["duplicate_stat_records_excluded"] == 2


def test_player_market_coverage_requires_every_component_in_the_same_game():
    histories = {
        "1": [
            {"game_id": "g1", "home_team_id": "1", "home": "Home", "kickoff": "2026-10-01T00:00:00Z", "completed": True},
            {"game_id": "g2", "home_team_id": "1", "home": "Home", "kickoff": "2026-10-02T00:00:00Z", "completed": True},
            {"game_id": "g3", "home_team_id": "1", "home": "Home", "kickoff": "2026-10-03T00:00:00Z", "completed": True},
        ]
    }
    reports = {
        "g1": {"available": True, "teams": [{"team_id": "1", "players": [
            {"player_id": "p1", "name": "Player", "points": 20, "rebounds": 6, "assists": None, "blocks": 1, "steals": 2}
        ]}]},
        "g2": {"available": True, "teams": [{"team_id": "1", "players": [
            {"player_id": "p1", "name": "Player", "points": 18, "rebounds": 5, "assists": 4, "blocks": 0, "steals": 1}
        ]}]},
        "g3": {"available": True, "teams": [{"team_id": "1", "players": [
            {"player_id": "p1", "name": "Player", "points": None, "rebounds": 7, "assists": 3, "blocks": 2, "steals": 0}
        ]}]},
    }

    result = aggregate_player_projections(reports, histories)
    player = result["teams"][0]["players"][0]

    assert player["market_coverage_denominator"] == 3
    assert player["games_sampled_by_market"] == {
        "PTS": 2, "REB": 3, "AST": 2, "PRA": 1,
        "PR": 2, "PA": 1, "RA": 2, "BLK": 3, "STL": 3,
    }
    assert len(player["market_history"]) == 3
