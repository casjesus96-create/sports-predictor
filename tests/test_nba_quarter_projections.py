from nba_analyzer import _build_projections, _team_metrics


def test_team_metrics_calculates_quarter_averages_from_pregame_boxscores():
    games = [
        {"game_id": "g1", "home_team_id": "h", "away_team_id": "a", "kickoff": "2026-01-01T00:00:00+00:00", "home_score": 100, "away_score": 90},
    ]
    boxscores = [{
        "game_id": "g1",
        "stats": {"_quarter_points": [25, 24, 26, 25]},
        "opponent_stats": {"_quarter_points": [20, 22, 23, 25]},
    }]
    metrics = _team_metrics("h", games, boxscores)
    assert metrics["quarter_points_for_per_game"] == [25.0, 24.0, 26.0, 25.0]
    assert metrics["quarter_points_against_per_game"] == [20.0, 22.0, 23.0, 25.0]
    assert metrics["quarter_games_sampled"] == 1


def test_build_projections_estimates_each_quarter_from_team_for_and_against():
    home = {
        "recent_points_for_per_game": 100,
        "recent_points_against_per_game": 95,
        "recent_stats_per_game": {},
        "recent_games": 5,
        "quarter_points_for_per_game": [25, 24, 26, 25],
        "quarter_points_against_per_game": [20, 22, 23, 25],
        "quarter_games_sampled": 5,
    }
    away = {
        "recent_points_for_per_game": 90,
        "recent_points_against_per_game": 100,
        "recent_stats_per_game": {},
        "recent_games": 5,
        "quarter_points_for_per_game": [22, 23, 24, 21],
        "quarter_points_against_per_game": [25, 24, 26, 25],
        "quarter_games_sampled": 4,
    }
    projections = _build_projections({}, home, away)
    quarters = projections["quarter_points"]
    assert quarters["available"] is True
    assert [p["label"] for p in quarters["periods"]] == ["Q1", "Q2", "Q3", "Q4"]
    assert quarters["periods"][0]["home_points"] == 25.0
    assert quarters["periods"][0]["away_points"] == 21.0


def test_quarter_projection_is_unavailable_when_no_quarter_data_exists():
    history = {
        "recent_points_for_per_game": 100,
        "recent_points_against_per_game": 95,
        "recent_stats_per_game": {},
        "recent_games": 5,
        "quarter_points_for_per_game": [None, None, None, None],
        "quarter_points_against_per_game": [None, None, None, None],
        "quarter_games_sampled": 0,
    }
    projections = _build_projections({}, history, history)
    assert projections["quarter_points"]["available"] is False
    assert all(p["home_points"] is None and p["away_points"] is None for p in projections["quarter_points"]["periods"])
