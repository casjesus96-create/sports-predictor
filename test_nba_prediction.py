import math

from nba_prediction import MODEL_VERSION, predict_winner


def test_probabilities_sum_to_one_and_are_bounded():
    history = {"games": 12, "point_diff_per_game": 4.5, "recent_point_diff_per_game": 5.0, "win_rate": .7, "recent_win_rate": .8, "recent_games": 5}
    result = predict_winner(history, history)
    assert result["model_version"] == MODEL_VERSION
    assert 0.08 <= result["home_probability"] <= 0.92
    assert math.isclose(result["home_probability"] + result["away_probability"], 1.0, abs_tol=0.0001)


def test_home_advantage_is_not_used_at_neutral_site():
    neutral = {"games": 10, "point_diff_per_game": 0, "recent_point_diff_per_game": 0, "win_rate": .5, "recent_win_rate": .5, "recent_games": 5}
    home = predict_winner(neutral, neutral, neutral_site=False)
    neutral_site = predict_winner(neutral, neutral, neutral_site=True)
    assert home["home_probability"] > neutral_site["home_probability"]


def test_small_sample_is_regularized():
    empty = {"games": 0, "point_diff_per_game": 0, "recent_point_diff_per_game": 0, "win_rate": .5, "recent_win_rate": .5, "recent_games": 0}
    result = predict_winner(empty, empty)
    assert result["data_quality"] <= 35
    assert 0.5 < result["home_probability"] < 0.6



def test_recent_boxscore_stats_influence_model_probability():
    neutral = {
        "games": 12,
        "point_diff_per_game": 0,
        "recent_point_diff_per_game": 0,
        "win_rate": 0.5,
        "recent_win_rate": 0.5,
        "recent_games": 5,
        "recent_stats_per_game": {
            "rebounds": 45,
            "assists": 29,
            "blocks": 7,
            "steals": 9,
            "turnovers": 10,
            "field_goal_pct": 49,
            "three_point_pct": 38,
            "free_throw_pct": 80,
        },
    }
    weak = {
        **neutral,
        "recent_stats_per_game": {
            "rebounds": 38,
            "assists": 20,
            "blocks": 2,
            "steals": 5,
            "turnovers": 17,
            "field_goal_pct": 42,
            "three_point_pct": 31,
            "free_throw_pct": 72,
        },
    }

    result = predict_winner(neutral, weak, neutral_site=True)

    assert result["model_version"] == "NBA-1.1.0"
    assert result["recent_boxscore_edge"] > 0
    assert result["home_probability"] > 0.5
