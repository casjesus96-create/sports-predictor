import pytest

from nba_player_market_model import (
    evaluate_over_under,
    evaluate_player_market,
    extract_pregame_market_observations,
)


def test_over_under_probabilities_are_smoothed_and_sum_with_push():
    result = evaluate_over_under([10, 12, 8, 10, 14, 7], 10)
    assert result["available"] is True
    assert result["method"] == "EMPIRICAL_BETA_SMOOTHED"
    assert result["sample_size"] == 6
    assert result["over"]["count"] == 2
    assert result["under"]["count"] == 2
    assert result["push"]["count"] == 2
    assert result["push"]["probability"] == pytest.approx(2 / 6, abs=1e-4)
    assert result["over"]["probability"] + result["under"]["probability"] + result["push"]["probability"] == pytest.approx(1.0, abs=1e-4)


def test_half_point_line_has_no_pushes():
    result = evaluate_over_under([8, 9, 10, 11, 12], 9.5)
    assert result["available"] is True
    assert result["push"]["count"] == 0
    assert result["push"]["probability"] == 0
    assert result["over"]["count"] == 3
    assert result["under"]["count"] == 2


def test_small_sample_is_not_given_a_probability():
    result = evaluate_over_under([10, 11, 12, 13], 10)
    assert result["available"] is False
    assert result["reason"] == "INSUFFICIENT_SAMPLE"
    assert result["sample_size"] == 4
    assert "over" not in result


def test_invalid_observations_are_excluded_without_fabricating_values():
    result = evaluate_over_under([10, None, "bad", float("nan"), 12, 8, 9, 11], 9.5)
    assert result["available"] is True
    assert result["sample_size"] == 5
    assert result["over"]["count"] == 3
    assert result["under"]["count"] == 2


@pytest.mark.parametrize("line", [None, "bad", -1, float("inf"), float("nan")])
def test_invalid_lines_are_rejected(line):
    result = evaluate_over_under([1, 2, 3, 4, 5], line)
    assert result["available"] is False
    assert result["reason"] == "INVALID_LINE_OR_MINIMUM"


def test_all_push_sample_reports_no_decisive_probability():
    result = evaluate_over_under([10, 10, 10, 10, 10], 10)
    assert result["available"] is True
    assert result["push"]["probability"] == 1.0
    assert result["over"]["probability"] == 0.0
    assert result["under"]["probability"] == 0.0


def _game(game_id, day, **stats):
    return {
        "game_id": game_id,
        "kickoff": f"2026-11-{day:02d}T00:00:00Z",
        "completed": True,
        **stats,
    }


def test_extract_market_series_uses_only_completed_games_before_cutoff():
    records = [
        _game("g1", 1, points=10, rebounds=5, assists=4),
        _game("g2", 2, points=20, rebounds=7, assists=3),
        _game("target", 3, points=99, rebounds=9, assists=9),
        {**_game("live", 2, points=30, rebounds=8, assists=5), "completed": False},
        {**_game("missing", 2, points=15, rebounds=None, assists=2)},
    ]
    result = extract_pregame_market_observations(
        records, "PRA", "2026-11-03T00:00:00Z"
    )
    assert result["available"] is True
    assert [row["game_id"] for row in result["observations"]] == ["g2", "g1"]
    assert [row["value"] for row in result["observations"]] == [30.0, 19.0]
    assert result["excluded"]["at_or_after_cutoff"] == 1
    assert result["excluded"]["not_completed"] == 1
    assert result["excluded"]["missing_or_invalid_stats"] == 1


@pytest.mark.parametrize(
    ("market", "expected"),
    [
        ("PTS", 20), ("REB", 7), ("AST", 3), ("PRA", 30),
        ("PR", 27), ("PA", 23), ("RA", 10), ("BLK", 2), ("STL", 1),
    ],
)
def test_extracts_supported_single_and_combo_markets(market, expected):
    result = extract_pregame_market_observations(
        [_game("g1", 1, points=20, rebounds=7, assists=3, blocks=2, steals=1)],
        market,
        "2026-11-02T00:00:00Z",
    )
    assert result["available"] is True
    assert result["observations"][0]["value"] == expected


def test_missing_combo_component_is_not_treated_as_zero():
    result = extract_pregame_market_observations(
        [_game("g1", 1, points=20, rebounds=7)],
        "PRA",
        "2026-11-02T00:00:00Z",
    )
    assert result["available"] is False
    assert result["excluded"]["missing_or_invalid_stats"] == 1


def test_duplicate_game_ids_are_counted_once():
    records = [
        _game("g1", 1, points=10),
        _game("g1", 1, points=50),
    ]
    result = extract_pregame_market_observations(
        records, "PTS", "2026-11-02T00:00:00Z"
    )
    assert result["sample_size"] == 1
    assert result["observations"][0]["value"] == 10
    assert result["excluded"]["duplicate_game"] == 1


def test_invalid_cutoff_and_market_are_rejected():
    assert extract_pregame_market_observations([], "PTS", "invalid")["reason"] == "INVALID_CUTOFF"
    assert extract_pregame_market_observations([], "XYZ", "2026-11-02T00:00:00Z")["reason"] == "UNSUPPORTED_MARKET"


def test_evaluate_player_market_combines_pregame_filtering_and_probability():
    records = [
        _game(1, 1, points=10),
        _game(2, 2, points=12),
        _game(3, 3, points=8),
        _game(4, 4, points=11),
        _game(5, 5, points=13),
        _game(6, 6, points=100),
    ]
    result = evaluate_player_market(
        records, "PTS", 10, "2026-11-06T00:00:00Z", min_sample=5
    )
    assert result["available"] is True
    assert result["market"] == "PTS"
    assert result["history_sample_size"] == 5
    assert result["sample_size"] == 5
    assert result["over"]["count"] == 3
    assert result["under"]["count"] == 1
    assert result["push"]["count"] == 1
    assert result["excluded"]["at_or_after_cutoff"] == 1


def test_evaluate_player_market_does_not_emit_probability_for_small_history():
    result = evaluate_player_market(
        [_game(1, 1, points=10), _game(2, 2, points=12)],
        "PTS",
        10,
        "2026-11-03T00:00:00Z",
    )
    assert result["available"] is False
    assert result["reason"] == "INSUFFICIENT_SAMPLE"
    assert "over" not in result
