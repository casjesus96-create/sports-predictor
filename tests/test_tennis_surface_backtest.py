from copy import deepcopy

import pytest

from tennis_surface_backtest import evaluate_surface_rows


def match(day, winner, loser, surface="Hard", score="6-4 6-4"):
    return {
        "tourney_date": day,
        "winner_name": winner,
        "loser_name": loser,
        "surface": surface,
        "score": score,
    }


def test_surface_backtest_is_research_only_and_reports_both_models():
    rows = [
        match("20240101", "A", "B"),
        match("20240102", "A", "B"),
        match("20240103", "B", "A"),
        match("20240104", "A", "B", "Clay"),
    ]
    result = evaluate_surface_rows(
        rows, "2024-01-03", "2024-01-04", min_surface_matches=1
    )

    assert result["success"] is True
    assert result["model_status"] == "research_only"
    assert result["evaluation"]["general_elo"]["matches_evaluated"] == 2
    assert result["evaluation"]["surface_elo_with_fallback"]["matches_evaluated"] == 2
    assert len(result["evaluation"]["monthly_breakdown"]) == 1
    assert result["surface_coverage"]["Hard"]["evaluated_with_surface_ratings"] >= 1
    assert result["surface_coverage"]["Clay"]["fallback_to_general_elo"] == 1


def test_same_date_order_does_not_change_metrics():
    rows = [
        match("20240101", "A", "B", "Hard"),
        match("20240101", "C", "D", "Clay"),
        match("20240102", "A", "C", "Hard"),
        match("20240102", "D", "B", "Clay"),
        match("20240103", "A", "B", "Hard"),
    ]
    first = evaluate_surface_rows(rows, "2024-01-02", "2024-01-03", min_surface_matches=1)
    second = evaluate_surface_rows(list(reversed(deepcopy(rows))), "2024-01-02", "2024-01-03", min_surface_matches=1)

    assert first["evaluation"] == second["evaluation"]
    assert first["surface_coverage"] == second["surface_coverage"]


def test_unknown_surface_falls_back_to_general_elo():
    rows = [
        match("20240101", "A", "B", "Carpet"),
        match("20240102", "A", "B", ""),
    ]
    result = evaluate_surface_rows(rows, "2024-01-02", "2024-01-02")

    assert result["evaluation"]["general_elo"] == result["evaluation"]["surface_elo_with_fallback"]
    assert result["surface_coverage"]["unknown"]["fallback_to_general_elo"] == 1


@pytest.mark.parametrize("minimum", [0, 101, True])
def test_rejects_invalid_surface_history_threshold(minimum):
    with pytest.raises(ValueError):
        evaluate_surface_rows([], "2024-01-01", "2024-01-01", min_surface_matches=minimum)


def test_surface_probability_blends_are_research_only_and_report_fixed_weights():
    rows = [
        match("20240101", "A", "B", "Hard"),
        match("20240102", "A", "B", "Hard"),
        match("20240103", "B", "A", "Hard"),
        match("20240104", "A", "C", "Clay"),
        match("20240105", "C", "B", "Clay"),
        match("20240106", "A", "B", "Hard"),
    ]
    result = evaluate_surface_rows(
        rows, "2024-01-03", "2024-01-06", min_surface_matches=1
    )

    blends = result["evaluation"]["surface_elo_blends"]
    assert set(blends) == {"25%", "50%", "75%"}
    assert result["model_status"] == "research_only"
    for label, expected_weight in (("25%", 0.25), ("50%", 0.5), ("75%", 0.75)):
        assert blends[label]["surface_weight"] == expected_weight
        assert blends[label]["metrics"]["matches_evaluated"] == 4
        assert "brier_improvement_vs_general" in blends[label]
        assert "log_loss_improvement_vs_general" in blends[label]
        assert all(
            f"surface_elo_blend_{int(expected_weight * 100)}" in month
            for month in result["evaluation"]["monthly_breakdown"]
        )


def test_blends_equal_general_when_all_surface_rows_fallback():
    rows = [
        match("20240101", "A", "B", "Carpet"),
        match("20240102", "A", "B", ""),
        match("20240103", "B", "A", "unknown"),
    ]
    result = evaluate_surface_rows(rows, "2024-01-02", "2024-01-03")

    general = result["evaluation"]["general_elo"]
    for blend in result["evaluation"]["surface_elo_blends"].values():
        assert blend["metrics"] == general


def test_rejects_period_over_366_days():
    with pytest.raises(ValueError):
        evaluate_surface_rows([], "2023-01-01", "2024-01-02")
