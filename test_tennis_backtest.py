from datetime import date, timedelta

import pytest

from tennis_backtest import _elo_probability, evaluate_rows


def row(day, winner, loser, score="6-4 6-4"):
    return {
        "tourney_date": day.strftime("%Y%m%d"),
        "winner_name": winner,
        "loser_name": loser,
        "score": score,
    }


def test_elo_probability_is_symmetric_and_half_for_equal_ratings():
    assert _elo_probability(1500, 1500) == 0.5
    assert _elo_probability(1600, 1500) > 0.5
    assert _elo_probability(1500, 1600) < 0.5
    assert _elo_probability(1600, 1500) + _elo_probability(1500, 1600) == pytest.approx(1.0)


def test_backtest_only_scores_matches_inside_evaluation_window():
    start = date(2026, 1, 2)
    rows = [
        row(date(2026, 1, 1), "A", "B"),
        row(date(2026, 1, 2), "A", "C"),
        row(date(2026, 1, 3), "B", "C"),
        row(date(2026, 1, 4), "C", "A"),
    ]
    result = evaluate_rows(rows, start, date(2026, 1, 3))
    assert result["evaluation"]["matches_evaluated"] == 2
    assert result["evaluation"]["dates_evaluated"] == 2
    assert result["model_status"] == "research_only"
    assert result["model"] == "tennis-elo-baseline-research"
    assert result["evaluation"]["benchmark"]["name"] == "50_50_coin_flip"
    assert result["evaluation"]["benchmark"]["brier_score"] == 0.25


def test_same_date_results_do_not_change_predictions_for_other_matches_same_date():
    day = date(2026, 1, 2)
    base = [row(day, "A", "B"), row(day, "C", "D")]
    reversed_order = list(reversed(base))
    first = evaluate_rows(base, day, day)
    second = evaluate_rows(reversed_order, day, day)
    assert first["examples"] == second["examples"]
    assert first["evaluation"]["matches_evaluated"] == 2


def test_walkovers_are_excluded():
    day = date(2026, 1, 2)
    result = evaluate_rows([row(day, "A", "B", "W/O")], day, day)
    assert result["evaluation"]["matches_evaluated"] == 0
    assert result["evaluation"]["accuracy"] is None
    assert result["data_quality"]["matches_excluded_walkover"] == 1


@pytest.mark.parametrize(
    "start,end,k_factor",
    [
        ("2026-01-03", "2026-01-02", 32),
        ("2026-01-01", "2027-02-01", 32),
        ("2026-01-01", "2026-01-02", 100),
    ],
)
def test_backtest_rejects_invalid_ranges_and_parameters(start, end, k_factor):
    with pytest.raises(ValueError):
        evaluate_rows([], start, end, k_factor)



def test_equal_rating_matches_receive_half_accuracy_credit():
    day = date(2026, 1, 2)
    result = evaluate_rows([row(day, "A", "B")], day, day)
    assert result["evaluation"]["accuracy"] == 0.5
    assert result["evaluation"]["brier_score"] == 0.25
    assert result["evaluation"]["log_loss"] == pytest.approx(0.693147, abs=1e-6)
    assert result["evaluation"]["benchmark"]["elo_brier_improvement"] == 0.0


def test_data_quality_reports_walkovers_and_invalid_rows():
    day = date(2026, 1, 2)
    rows = [
        row(day, "A", "B"),
        row(day, "C", "D", "W/O"),
        row(day, "", "E"),
        {"tourney_date": "bad-date", "winner_name": "F", "loser_name": "G", "score": "6-2"},
    ]
    result = evaluate_rows(rows, day, day)
    quality = result["data_quality"]
    assert quality["historical_rows_seen"] == 4
    assert quality["valid_matches_available_through_end_date"] == 1
    assert quality["matches_excluded_walkover"] == 1
    assert quality["matches_excluded_invalid"] == 1
    assert quality["rows_without_valid_date"] == 1
    assert quality["evaluation_matches"] == 1
