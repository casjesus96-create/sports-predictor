from datetime import date, datetime, timezone, timedelta

import pytest

import tennis_surface_validation as validation
from tennis_surface_backtest import _normalize_surface


def match(day, winner, loser, surface="Hard"):
    return {
        "tourney_date": day,
        "winner_name": winner,
        "loser_name": loser,
        "surface": surface,
        "score": "6-4 6-4",
    }


def test_calibration_uses_consistent_player_orientation():
    rows = [(0.79, 1), (0.71, 1), (0.21, 0), (0.29, 0)]
    bins = validation._calibration(rows)
    assert sum(item["matches"] for item in bins) == 4
    assert bins[2]["matches"] == 2
    assert bins[2]["observed_win_rate"] == 0.0
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


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Hard", "Hard"),
        (" hard ", "Hard"),
        ("CLAY", "Clay"),
        (" clay ", "Clay"),
        ("Grass Court", "Grass"),
        ("Carpet", None),
        ("", None),
        (None, None),
    ],
)
def test_surface_normalization_is_case_and_whitespace_insensitive(value, expected):
    assert _normalize_surface(value) == expected


def test_year_evaluation_reports_raw_and_normalized_surface_labels():
    day = date(2024, 2, 1)
    rows = [
        match(day.strftime("%Y%m%d"), "A", "B", "Clay"),
        match(day.strftime("%Y%m%d"), "C", "D", " clay "),
        match(day.strftime("%Y%m%d"), "E", "F", ""),
        match(day.strftime("%Y%m%d"), "G", "H", "Carpet"),
    ]

    result = validation._evaluate_year(
        rows, 2024, k_factor=32.0, min_surface_matches=10
    )

    assert result["raw_surface_labels_in_evaluation_window"] == {
        "<blank>": 1,
        " clay ": 1,
        "Carpet": 1,
        "Clay": 1,
    }
    assert result["normalized_surface_labels_in_evaluation_window"] == {
        "Clay": 2,
        "<unknown>": 2,
    }
    assert result["matches_evaluated"] == 4


def test_current_year_holdout_uses_one_utc_snapshot_and_stops_yesterday(monkeypatch):
    as_of = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return as_of if tz else as_of.replace(tzinfo=None)

    rows = [
        match("20261014", "A", "B", "Hard"),
        match("20261015", "C", "D", " clay "),
    ]

    monkeypatch.setattr(validation, "datetime", FixedDateTime)
    monkeypatch.setattr(validation, "load_year", lambda league, year: rows if year == 2026 else [])

    result = validation.run_chronological_surface_validation("WTA")

    holdout = next(window for window in result["windows"] if window["year"] == 2026)
    assert result["protocol"]["as_of_date_utc"] == "2026-10-15"
    assert result["protocol"]["holdout_cutoff_exclusive"] == "2026-10-15"
    assert result["protocol"]["holdout_evaluation_end_date"] == "2026-10-14"
    assert holdout["evaluation_end_date"] == "2026-10-14"
    assert holdout["matches_evaluated"] == 1
    assert holdout["raw_surface_labels_in_evaluation_window"] == {"Hard": 1}
    assert holdout["normalized_surface_labels_in_evaluation_window"] == {"Hard": 1}
    assert holdout["role"] == "holdout_partial_year"
