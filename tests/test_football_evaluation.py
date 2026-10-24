from football_evaluation_api import evaluate_rows


def row(home, draw, away, hs, aws, competition="PL"):
    return {
        "home_probability": home, "draw_probability": draw, "away_probability": away,
        "actual_home_score": hs, "actual_away_score": aws,
        "competition_code": competition,
    }


def test_evaluation_computes_metrics_and_groups_competition():
    result = evaluate_rows([
        row(0.7, 0.2, 0.1, 2, 0),
        row(0.2, 0.5, 0.3, 1, 1, "PD"),
        row(0.1, 0.2, 0.7, 0, 2),
    ])
    assert result["sample_size"] == 3
    assert result["metrics"]["accuracy"] == 1
    assert result["metrics"]["brier_score"] >= 0
    assert result["metrics"]["log_loss"] > 0
    assert set(result["by_outcome"]) == {"home", "draw", "away"}
    assert set(result["by_competition"]) == {"PL", "PD"}
    assert result["status"] == "insufficient_data"


def test_evaluation_skips_invalid_rows_and_handles_empty_input():
    result = evaluate_rows([
        row(0.8, 0.3, 0.1, 1, 0),
        row(0.5, 0.3, 0.2, None, 0),
    ])
    assert result["sample_size"] == 0
    assert result["skipped_rows"] == 2
    assert result["metrics"] is None
    assert result["status"] == "insufficient_data"


def test_evaluation_normalizes_small_probability_rounding_difference():
    result = evaluate_rows([row(0.6, 0.2, 0.21, 1, 0)])
    assert result["sample_size"] == 1
    assert result["metrics"]["accuracy"] == 1
