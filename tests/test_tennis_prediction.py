import pytest

from tennis_prediction import (
    DEFAULT_K_FACTOR,
    INITIAL_RATING,
    build_pre_match_ratings,
    elo_probability,
    project_match,
)


def row(day, winner, loser, score="6-4 6-4"):
    return {
        "tourney_date": day.replace("-", ""),
        "winner_name": winner,
        "loser_name": loser,
        "score": score,
        "surface": "Hard",
    }


def test_equal_ratings_produce_half_probability():
    assert elo_probability(INITIAL_RATING, INITIAL_RATING) == pytest.approx(0.5)


def test_cutoff_is_exclusive_and_walkovers_are_excluded():
    rows = [
        row("2025-01-01", "Player A", "Player B"),
        row("2025-01-02", "Player A", "Player C"),
        row("2025-01-01", "Player B", "Player C", "Walkover"),
    ]
    state = build_pre_match_ratings(rows, "2025-01-02")
    assert state["matches_used"] == 1
    assert state["excluded"]["on_or_after_cutoff"] == 1
    assert state["excluded"]["invalid_match"] == 1


def test_projection_probabilities_sum_to_one():
    state = build_pre_match_ratings(
        [row("2025-01-01", "Player A", "Player B")],
        "2025-01-02",
    )
    prediction = project_match("Player A", "Player B", state)
    total = (
        prediction["player1"]["win_probability"]
        + prediction["player2"]["win_probability"]
    )
    assert total == pytest.approx(1.0)
    assert prediction["player1"]["win_probability"] > 0.5


def test_name_normalization_is_used_for_lookup():
    state = build_pre_match_ratings(
        [row("2025-01-01", "Joao Sousa", "Player B")],
        "2025-01-02",
    )
    prediction = project_match("João Sousa", "Player B", state)
    assert prediction["player1"]["rating"] > INITIAL_RATING


def test_invalid_k_factor_is_rejected():
    with pytest.raises(ValueError):
        build_pre_match_ratings([], "2025-01-02", k_factor=100)


def test_same_date_matches_use_frozen_ratings():
    first_order = [
        row("2025-01-01", "Player A", "Player B"),
        row("2025-01-01", "Player B", "Player C"),
    ]
    second_order = list(reversed(first_order))
    state_a = build_pre_match_ratings(first_order, "2025-01-02", DEFAULT_K_FACTOR)
    state_b = build_pre_match_ratings(second_order, "2025-01-02", DEFAULT_K_FACTOR)
    assert state_a["ratings"] == pytest.approx(state_b["ratings"])
