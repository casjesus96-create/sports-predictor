import pytest

from nba_player_market_model import evaluate_over_under


def test_over_under_probabilities_are_smoothed_and_sum_with_push():
    result = evaluate_over_under([10, 12, 8, 10, 14, 7], 10)
    assert result["available"] is True
    assert result["method"] == "EMPIRICAL_BETA_SMOOTHED"
    assert result["sample_size"] == 6
    assert result["over"]["count"] == 2
    assert result["under"]["count"] == 2
    assert result["push"]["count"] == 2
    assert result["push"]["probability"] == pytest.approx(2 / 6)
    assert result["over"]["probability"] + result["under"]["probability"] + result["push"]["probability"] == pytest.approx(1.0)


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
