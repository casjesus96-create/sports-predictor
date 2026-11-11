import nfl_repository


def _row(home_probability, away_probability, result="CORRECT", actual="BUF"):
    return {
        "result_status": "SETTLED",
        "prediction_result": result,
        "actual_winner": actual,
        "home_probability": home_probability,
        "away_probability": away_probability,
        "features": {"predicted_winner": "BUF"},
    }


def test_wilson_interval_matches_known_one_of_three_sample():
    assert nfl_repository._wilson_interval(1, 3) == {
        "lower": 0.0615,
        "upper": 0.7923,
    }


def test_nfl_calibration_reports_wilson_and_excludes_pushes_and_invalid_rows(monkeypatch):
    rows = [
        _row(0.52, 0.48, "CORRECT"),
        _row(0.54, 0.46, "INCORRECT", actual="MIA"),
        _row(0.63, 0.37, "CORRECT"),
        _row(0.91, 0.09, "CORRECT"),
        _row(0.50, 0.50, "PUSH", actual="TIE"),
        _row(None, 0.60, "CORRECT"),
        _row(0.99, 0.01, "CORRECT"),
        {"result_status": "PENDING", "home_probability": 0.8, "away_probability": 0.2},
    ]
    monkeypatch.setattr(nfl_repository, "get_nfl_predictions", lambda **kwargs: rows)

    result = nfl_repository.get_nfl_calibration(minimum_sample=30)

    assert result["sample_size"] == 4
    assert result["observed_accuracy"] == 0.75
    assert result["accuracy_ci_95"] == nfl_repository._wilson_interval(3, 4)
    assert result["invalid_probability_rows"] == 2
    assert [item["range"] for item in result["calibration"]] == [
        "50%-55%", "60%-65%", "90%-95%"
    ]
    assert all(item["accuracy_ci_95"] for item in result["calibration"])
    assert all(item["small_sample"] for item in result["calibration"])
    assert result["calibration_ready"] is False
    assert result["read_only"] is True
    assert result["official_probability_changed"] is False


def test_nfl_calibration_marks_minimum_sample_without_recalibrating(monkeypatch):
    rows = [
        _row(0.70, 0.30, "CORRECT" if index % 2 == 0 else "INCORRECT",
             actual="BUF" if index % 2 == 0 else "MIA")
        for index in range(30)
    ]
    monkeypatch.setattr(nfl_repository, "get_nfl_predictions", lambda **kwargs: rows)

    result = nfl_repository.get_nfl_calibration(minimum_sample=30)

    assert result["sample_size"] == 30
    assert result["calibration_ready"] is True
    assert result["official_probability_changed"] is False


def test_nfl_calibration_handles_empty_history(monkeypatch):
    monkeypatch.setattr(nfl_repository, "get_nfl_predictions", lambda **kwargs: [])
    result = nfl_repository.get_nfl_calibration()
    assert result["sample_size"] == 0
    assert result["observed_accuracy"] is None
    assert result["accuracy_ci_95"] is None
    assert result["calibration"] == []
    assert result["calibration_ready"] is False

def test_nfl_calibration_diagnoses_overconfidence_only_when_wilson_is_below_confidence(monkeypatch):
    rows = [
        _row(0.90, 0.10, "INCORRECT", actual="MIA")
        for _ in range(30)
    ]
    monkeypatch.setattr(nfl_repository, "get_nfl_predictions", lambda **kwargs: rows)

    result = nfl_repository.get_nfl_calibration(minimum_sample=30)

    assert result["confidence_diagnosis"] == "OVERCONFIDENT"
    assert result["average_confidence"] == 0.90
    assert result["calibration"][0]["confidence_diagnosis"] == "OVERCONFIDENT"
    assert result["read_only"] is True
    assert result["official_probability_changed"] is False


def test_nfl_calibration_keeps_overlapping_wilson_interval_inconclusive(monkeypatch):
    rows = [
        _row(0.70, 0.30, "CORRECT" if index < 18 else "INCORRECT",
             actual="BUF" if index < 18 else "MIA")
        for index in range(30)
    ]
    monkeypatch.setattr(nfl_repository, "get_nfl_predictions", lambda **kwargs: rows)

    result = nfl_repository.get_nfl_calibration(minimum_sample=30)

    assert result["confidence_diagnosis"] == "INCONCLUSIVE"
    assert result["calibration"][0]["confidence_diagnosis"] == "INCONCLUSIVE"


def test_nfl_calibration_marks_band_with_small_sample_as_insufficient(monkeypatch):
    rows = [
        _row(0.90, 0.10, "INCORRECT", actual="MIA")
        for _ in range(9)
    ]
    monkeypatch.setattr(nfl_repository, "get_nfl_predictions", lambda **kwargs: rows)

    result = nfl_repository.get_nfl_calibration(minimum_sample=30)

    assert result["confidence_diagnosis"] == "INSUFFICIENT_SAMPLE"
    assert result["calibration"][0]["confidence_diagnosis"] == "INSUFFICIENT_SAMPLE"


def _temporal_observation(kickoff, confidence=0.7, correct=True):
    return {"kickoff": kickoff, "confidence": confidence, "correct": correct}


def test_nfl_temporal_calibration_splits_chronologically_and_keeps_dates_together():
    observations = []
    for day in range(1, 5):
        for index in range(20):
            observations.append(_temporal_observation(
                f"2026-09-{day:02d}T18:00:00Z",
                confidence=0.8 if day <= 2 else 0.6,
                correct=day > 2,
            ))

    result = nfl_repository.build_nfl_temporal_calibration_stability(
        observations, minimum_per_window=30
    )

    assert result["eligible"] is True
    assert [window["sample_size"] for window in result["windows"]] == [40, 40]
    assert result["split_before"] == "2026-09-03"
    assert result["windows"][0]["mean_confidence"] == 0.8
    assert result["windows"][0]["observed_accuracy"] == 0.0
    assert result["windows"][1]["mean_confidence"] == 0.6
    assert result["windows"][1]["observed_accuracy"] == 1.0
    assert all(window["accuracy_ci_95"] for window in result["windows"])
    assert result["read_only"] is True
    assert result["official_probability_changed"] is False


def test_nfl_temporal_calibration_requires_two_sufficient_date_windows():
    observations = [
        _temporal_observation("2026-09-01T18:00:00Z")
        for _ in range(29)
    ]
    observations.append(_temporal_observation(None))

    result = nfl_repository.build_nfl_temporal_calibration_stability(
        observations, minimum_per_window=30
    )

    assert result["eligible"] is False
    assert result["windows"] == []
    assert result["sample_size"] == 29
    assert result["excluded_missing_kickoff"] == 1


def test_nfl_temporal_calibration_excludes_invalid_dates_and_observations():
    observations = [
        _temporal_observation("not-a-date"),
        _temporal_observation("2026-09-01T18:00:00Z", confidence=0.99),
        _temporal_observation("2026-09-02T18:00:00Z", correct=1),
    ]

    result = nfl_repository.build_nfl_temporal_calibration_stability(observations)

    assert result["eligible"] is False
    assert result["sample_size"] == 0
    assert result["excluded_invalid_observation"] == 3
    assert result["official_probability_changed"] is False


def test_nfl_calibration_includes_kickoff_temporal_stability(monkeypatch):
    rows = []
    for day in range(1, 5):
        for index in range(20):
            row = _row(
                0.8 if day <= 2 else 0.6,
                0.2 if day <= 2 else 0.4,
                "INCORRECT" if day <= 2 else "CORRECT",
                actual="MIA" if day <= 2 else "BUF",
            )
            row["features"]["game"] = {"kickoff": f"2026-09-{day:02d}T18:00:00Z"}
            rows.append(row)
    monkeypatch.setattr(nfl_repository, "get_nfl_predictions", lambda **kwargs: rows)

    result = nfl_repository.get_nfl_calibration(minimum_sample=30)

    assert result["temporal_stability"]["eligible"] is True
    assert [window["sample_size"] for window in result["temporal_stability"]["windows"]] == [40, 40]
    assert result["read_only"] is True
    assert result["official_probability_changed"] is False
