from batter_hit_projection import build_batter_hit_projections, calculate_one_plus_hit_probability


def test_one_plus_hit_probability_uses_avg_and_opportunities():
    probability = calculate_one_plus_hit_probability(0.25, 4)
    assert probability is not None
    assert round(probability, 4) == round(1 - 0.75 ** 4, 4)


def test_invalid_average_does_not_create_probability():
    assert calculate_one_plus_hit_probability(None, 4) is None
    assert calculate_one_plus_hit_probability(1.2, 4) is None
    assert calculate_one_plus_hit_probability(0.25, 0) is None


def test_unconfirmed_lineup_does_not_create_batter_props():
    result = build_batter_hit_projections({
        "home_team": {"lineup_confirmed": False, "hitters": [{"player_id": 1, "player_name": "Player", "batting_order": 1}]},
        "away_team": {"lineup_confirmed": False, "hitters": [{"player_id": 2, "player_name": "Player 2", "batting_order": 2}]},
    })
    assert result["available"] is False
    assert result["teams"] == []
    assert "No hay alineación confirmada" in result["note"]


def test_live_projection_uses_outs_and_team_batting_half(monkeypatch):
    import batter_hit_projection as module

    monkeypatch.setattr(module, "_fetch_season_hitting_stats", lambda ids, season: {
        player_id: {"season": season, "avg": 0.25, "at_bats": 100, "hits": 25}
        for player_id in ids
    })
    teams = [
        {"side": "away", "hitters": [
            {"player_id": 1, "player_name": "Away Batter", "batting_order": 1,
             "hits_in_game": 0, "at_bats_in_game": 2}
        ]},
        {"side": "home", "hitters": [
            {"player_id": 2, "player_name": "Home Batter", "batting_order": 1,
             "hits_in_game": 0, "at_bats_in_game": 2}
        ]},
    ]
    result = module.build_live_batter_hit_projections(
        teams, current_inning=7, inning_state="Top", game_status="Live",
        outs=2, active_batting_side="away",
    )
    away = result["teams"][0]["hitters"][0]
    home = result["teams"][1]["hitters"][0]
    assert away["estimated_team_innings_remaining"] == 2.33
    assert home["estimated_team_innings_remaining"] == 3.0
    assert away["expected_remaining_at_bats"] < home["expected_remaining_at_bats"]
    assert result["outs_used"] == 2
    assert result["active_batting_side"] == "away"


def test_live_projection_final_game_has_no_remaining_opportunities(monkeypatch):
    import batter_hit_projection as module

    monkeypatch.setattr(module, "_fetch_season_hitting_stats", lambda ids, season: {
        player_id: {"season": season, "avg": 0.25, "at_bats": 100, "hits": 25}
        for player_id in ids
    })
    result = module.build_live_batter_hit_projections(
        [{"side": "away", "hitters": [
            {"player_id": 1, "player_name": "Away Batter", "batting_order": 1,
             "hits_in_game": 0, "at_bats_in_game": 2}
        ]}],
        current_inning=9, inning_state="Bottom", game_status="Final",
        outs=2, active_batting_side="home",
    )
    hitter = result["teams"][0]["hitters"][0]
    assert hitter["expected_remaining_at_bats"] == 0.0
    assert hitter["probability_additional_hit_percent"] == 0.0
