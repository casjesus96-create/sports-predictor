import math

from run_projections import (
    calculate_game_projections,
    estimate_pitcher_strikeouts,
    parse_innings_pitched,
    poisson_probability_at_least,
    poisson_probability_exact,
    estimate_tie_after_nine_probability,
)


def test_mlb_innings_notation_converts_outs_not_decimal():
    assert parse_innings_pitched("100.0") == 100
    assert math.isclose(parse_innings_pitched("100.1"), 100 + 1 / 3)
    assert math.isclose(parse_innings_pitched("100.2"), 100 + 2 / 3)
    assert parse_innings_pitched("100.3") is None


def test_poisson_threshold_probabilities_are_valid_and_decrease():
    p5 = poisson_probability_at_least(5, 5.0)
    p6 = poisson_probability_at_least(6, 5.0)
    p7 = poisson_probability_at_least(7, 5.0)
    assert 0 <= p7 <= p6 <= p5 <= 1
    assert poisson_probability_at_least(5, 0) == 0


def test_run_and_pitcher_k_projections_use_available_stats():
    result = calculate_game_projections(
        home_hitting={"runs": 720, "gamesPlayed": 160, "strikeOuts": 1300, "atBats": 5400},
        away_hitting={"runs": 680, "gamesPlayed": 160, "strikeOuts": 1400, "atBats": 5350},
        home_pitching={"runs": 700, "gamesPlayed": 160},
        away_pitching={"runs": 750, "gamesPlayed": 160},
        home_form={"last_15": {"games": 15, "runs_scored_per_game": 4.8, "runs_allowed_per_game": 4.2}},
        away_form={"last_15": {"games": 15, "runs_scored_per_game": 4.3, "runs_allowed_per_game": 4.6}},
        home_pitcher_stats={"strikeOuts": 180, "inningsPitched": "180.0", "gamesStarted": 30},
        away_pitcher_stats={"strikeOuts": 150, "inningsPitched": "150.1", "gamesStarted": 29},
        home_pitcher_name="Home Starter",
        away_pitcher_name="Away Starter",
    )
    runs = result["run_projection"]
    assert runs["available"] is True
    assert runs["home"]["expected_runs"] > 0
    assert runs["away"]["expected_runs"] > 0
    assert runs["total_expected_runs"] == round(
        runs["home"]["expected_runs"] + runs["away"]["expected_runs"], 2
    )
    assert runs["projected_score"] is not None

    ks = result["pitcher_strikeout_projection"]
    assert ks["available"] is True
    assert ks["home_pitcher"]["pitcher_name"] == "Home Starter"
    assert ks["home_pitcher"]["expected_strikeouts"] == 6.0
    assert 0 <= ks["home_pitcher"]["probability_7_plus"] <= 1
    assert ks["home_pitcher"]["probability_5_plus"] >= ks["home_pitcher"]["probability_6_plus"]
    assert ks["home_pitcher"]["probability_6_plus"] >= ks["home_pitcher"]["probability_7_plus"]


def test_missing_stats_are_not_fabricated_as_zero():
    result = calculate_game_projections(
        home_hitting={},
        away_hitting={},
        home_pitching={},
        away_pitching={},
        home_form={},
        away_form={},
        home_pitcher_stats={},
        away_pitcher_stats={},
    )
    assert result["run_projection"]["available"] is False
    assert result["run_projection"]["total_expected_runs"] is None
    assert result["pitcher_strikeout_projection"]["available"] is False
    assert result["pitcher_strikeout_projection"]["home_pitcher"]["expected_strikeouts"] is None


def test_pitcher_projection_reports_opponent_k_rate_as_context_only():
    result = estimate_pitcher_strikeouts(
        {"strikeOuts": 100, "inningsPitched": "100.0", "gamesStarted": 20},
        {"strikeOuts": 900, "atBats": 4000},
        "Starter",
    )
    assert result["available"] is True
    assert result["opponent_strikeout_rate"] == 0.225
    assert "not used to adjust" in result["opponent_strikeout_rate_note"]


def test_poisson_exact_score_probabilities_are_valid():
    assert poisson_probability_exact(0, 0) == 1.0
    assert poisson_probability_exact(4, 0) == 0.0
    assert math.isclose(poisson_probability_exact(0, 4), math.exp(-4))
    assert poisson_probability_exact(-1, 4) is None


def test_tie_after_nine_probability_is_valid_and_symmetric():
    p_equal = estimate_tie_after_nine_probability(4.2, 4.2)
    p_swapped = estimate_tie_after_nine_probability(4.2, 3.8)
    p_reverse = estimate_tie_after_nine_probability(3.8, 4.2)
    assert 0 < p_equal < 1
    assert math.isclose(p_swapped, p_reverse, rel_tol=1e-12)
    assert estimate_tie_after_nine_probability(None, 4.0) is None
    assert estimate_tie_after_nine_probability(-1, 4.0) is None


def test_projected_score_keeps_decimal_expected_runs_and_tie_probability():
    result = calculate_game_projections(
        home_hitting={"runs": 704, "gamesPlayed": 160},
        away_hitting={"runs": 720, "gamesPlayed": 160},
        home_pitching={"runs": 688, "gamesPlayed": 160},
        away_pitching={"runs": 672, "gamesPlayed": 160},
        home_form={},
        away_form={},
        home_pitcher_stats={},
        away_pitcher_stats={},
    )
    runs = result["run_projection"]
    assert runs["projected_score"] == "4.4-4.3"
    assert 0 < runs["probability_tied_after_nine"] < 1
    assert "not an exact score prediction" in runs["note"]
