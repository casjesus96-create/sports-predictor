from datetime import date, datetime, timezone

import pytest

import tennis_surface_validation as validation
from tennis_surface_backtest import _normalize_surface


def match(day, winner="Player A", loser="Player B", surface="Hard", score="6-4 6-4"):
    return {
        "tourney_date": day.strftime("%Y%m%d"),
        "winner_name": winner,
        "loser_name": loser,
        "surface": surface,
        "score": score,
    }


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
        match(day, "A", "B", "Clay"),
        match(day, "C", "D", " clay "),
        match(day, "E", "F", ""),
        match(day, "G", "H", "Carpet"),
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
        match(date(2026, 10, 14), "A", "B", "Hard"),
        match(date(2026, 10, 15), "C", "D", " clay "),
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
