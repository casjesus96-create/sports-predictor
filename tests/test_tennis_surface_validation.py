from datetime import datetime, timezone, timedelta

import pytest

import tennis_surface_validation as validation


def match(day, winner, loser, surface="Hard"):
    return {
        "tourney_date": day,
        "winner_name": winner,
        "loser_name": loser,
        "surface": surface,
        "score": "6-4 6-4",
    }


def test_calibration_uses_consistent_player_orientation():
    rows = [(0.8, 1), (0.7, 1), (0.2, 0), (0.3, 0)]
    bins = validation._calibration(rows)
    assert sum(item["matches"] for item in bins) == 4
    assert bins[1]["matches"] == 2
    assert bins[1]["observed_win_rate"] == 0.0
    assert bins[7]["matches"] == 2
    assert bins[7]["observed_win_rate"] == 1.0


def test_validation_returns_calibration_surface_metrics_and_holdout(monkeypatch):
    current_year = datetime.now(timezone.utc).date().year
    data = {}
    for year in range(2020, current_year + 1):
        data[year] = (
            match(f"{year}0102", "Alice", "Bob", "Hard"),
            match(f"{year}0103", "Carol", "Dan", "Clay"),
            match(f"{year}0104", "Eve", "Frank", "Grass"),
            match(f"{year}0105", "Bob", "Alice", "Hard"),
        )

    monkeypatch.setattr(validation, "load_year", lambda league, year: data.get(year, ()))
    result = validation.run_chronological_surface_validation(
        "ATP",
        validation_years=(2023, 2024),
        reference_year=2025,
        holdout_year=current_year,
        warmup_years=3,
        min_surface_matches=1,
    )

    assert result["success"] is True
    assert result["model_status"] == "research_only"
    assert result["protocol"]["official_model_changed"] is False
    assert [item["year"] for item in result["windows"]] == [2023, 2024, 2025, current_year]
    assert result["windows"][0]["role"] == "validation"
    assert result["windows"][2]["role"] == "reference_seen_before"
    assert result["windows"][3]["role"] == "holdout_partial_year"
    assert result["windows"][3]["evaluation_end_date"] == (
        datetime.now(timezone.utc).date() - timedelta(days=1)
    ).isoformat()

    for window in result["windows"]:
        assert set(window["metrics"]) == set(validation.METHODS)
        assert set(window["calibration"]) == set(validation.METHODS)
        assert "Hard" in window["metrics_by_surface"]
        assert "Clay" in window["metrics_by_surface"]
        assert "Grass" in window["metrics_by_surface"]
        assert sum(item["matches"] for item in window["calibration"]["general_elo"]) == window["matches_evaluated"]


@pytest.mark.parametrize("minimum", [0, 101, True])
def test_validation_rejects_invalid_surface_threshold(monkeypatch, minimum):
    monkeypatch.setattr(validation, "load_year", lambda league, year: (match(f"{year}0102", "A", "B"),))
    with pytest.raises(ValueError):
        validation.run_chronological_surface_validation(
            "ATP", validation_years=(2023, 2024), reference_year=2025,
            holdout_year=2026, min_surface_matches=minimum,
        )
