"""Unit tests for paired bootstrap statistics in NFL score evaluation."""
from nfl_score_evaluation import _paired_bootstrap_ci


def test_paired_bootstrap_ci_is_deterministic():
    differences = [1.0, 0.5, 0.25, 1.25, 0.75]
    first = _paired_bootstrap_ci(differences, iterations=500, seed=17)
    second = _paired_bootstrap_ci(differences, iterations=500, seed=17)
    assert first == second
    assert first["iterations"] == 500
    assert first["lower"] <= first["upper"]


def test_positive_improvement_has_positive_interval_for_constant_values():
    result = _paired_bootstrap_ci([0.5] * 30, iterations=500, seed=18)
    assert result["lower"] == 0.5
    assert result["upper"] == 0.5


def test_empty_sample_returns_missing_interval():
    assert _paired_bootstrap_ci([]) == {
        "lower": None,
        "upper": None,
        "iterations": 0,
    }
