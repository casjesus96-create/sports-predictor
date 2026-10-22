from nba_player_impact import evaluate_player_impact


def test_returns_team_production_signals_without_changing_official_probability():
    projections = {
        "available": True,
        "teams": [
            {"team_id": "home", "team": "Home", "players": [
                {"name": "H1", "projected_points": 20, "projected_assists": 5,
                 "projected_rebounds": 8, "projected_blocks": 1, "projected_steals": 2},
                {"name": "H2", "projected_points": 10, "projected_assists": 3,
                 "projected_rebounds": 4, "projected_blocks": 0, "projected_steals": 1},
            ]},
            {"team_id": "away", "team": "Away", "players": [
                {"name": "A1", "projected_points": 15, "projected_assists": 4,
                 "projected_rebounds": 6, "projected_blocks": 2, "projected_steals": 1},
            ]},
        ],
    }
    result = evaluate_player_impact(projections, "home", "away")
    assert result["available"] is True
    assert result["official_probability_changed"] is False
    assert result["differences_home_minus_away"]["points"] == 15
    assert result["teams"]["home"]["player_appearance_coverage"]["points"] == 0
    assert result["differences_home_minus_away"]["assists"] == 4
    assert result["differences_home_minus_away"]["rebounds"] == 6
    assert result["differences_home_minus_away"]["blocks"] == -1
    assert result["differences_home_minus_away"]["steals"] == 2
    assert "probabilidad" in result["note"].lower()


def test_missing_projections_return_unavailable_and_no_adjustment():
    result = evaluate_player_impact({"available": False, "teams": []}, "home", "away")
    assert result["available"] is False
    assert result["official_probability_changed"] is False
    assert result["reason"] == "player_projections_unavailable"


def test_missing_stat_is_not_treated_as_zero():
    projections = {
        "available": True,
        "teams": [
            {"team_id": "home", "players": [{"name": "H", "projected_points": 12}]},
            {"team_id": "away", "players": [{"name": "A", "projected_points": 10}]},
        ],
    }
    result = evaluate_player_impact(projections, "home", "away")
    assert result["differences_home_minus_away"]["points"] == 2
    assert result["differences_home_minus_away"]["assists"] is None
