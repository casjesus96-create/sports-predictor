from experimental_probability import calculate_experimental_probability


def test_missing_context_preserves_official_probability():
    result = calculate_experimental_probability({"home": 0.61, "away": 0.39})

    assert result["home_probability"] == 0.61
    assert result["away_probability"] == 0.39
    assert result["available_components"] == 0
    assert result["status"] == "research_only"


def test_probability_sums_to_one_and_stays_bounded():
    result = calculate_experimental_probability(
        {"home": 0.94, "away": 0.06},
        matchup_data={
            "h2h": {
                "available": True,
                "games": 20,
                "home_team_wins": 18,
                "away_team_wins": 2,
            },
            "batting_splits": {
                "home_team": {"batting_split": {"available": True, "ops": 1.050}},
                "away_team": {"batting_split": {"available": True, "ops": 0.500}},
            },
            "bullpen": {"available": True, "signal": 1.0, "confidence": 1.0},
        },
    )

    assert 0.05 <= result["home_probability"] <= 0.95
    assert round(result["home_probability"] + result["away_probability"], 4) == 1.0


def test_batter_pitcher_data_requires_both_confirmed_lineups():
    matchup_data = {}
    unconfirmed = {
        "home_team": {
            "lineup_confirmed": False,
            "hitters": [{
                "vs_pitcher": {"available": True, "ops": 1.500, "plate_appearances": 100}
            }],
        },
        "away_team": {
            "lineup_confirmed": True,
            "hitters": [{
                "vs_pitcher": {"available": True, "ops": 0.200, "plate_appearances": 100}
            }],
        },
    }
    result = calculate_experimental_probability(
        {"home": 0.50, "away": 0.50},
        matchup_data=matchup_data,
        batter_pitcher_matchups=unconfirmed,
    )

    assert result["components"]["batter_vs_pitcher"]["available"] is False
    assert result["home_probability"] == 0.50


def test_h2h_adjustment_is_separate_and_directional():
    result = calculate_experimental_probability(
        {"home": 0.50, "away": 0.50},
        matchup_data={
            "h2h": {
                "available": True,
                "games": 10,
                "home_team_wins": 8,
                "away_team_wins": 2,
            }
        },
    )

    assert result["home_probability"] > 0.50
    assert result["components"]["h2h"]["available"] is True
