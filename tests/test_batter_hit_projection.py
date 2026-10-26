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
