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
    monkeypatch.setattr(nfl_repository, "get_nfl_predictions", lambda: rows)

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
    monkeypatch.setattr(nfl_repository, "get_nfl_predictions", lambda: rows)

    result = nfl_repository.get_nfl_calibration(minimum_sample=30)

    assert result["sample_size"] == 30
    assert result["calibration_ready"] is True
    assert result["official_probability_changed"] is False


def test_nfl_calibration_handles_empty_history(monkeypatch):
    monkeypatch.setattr(nfl_repository, "get_nfl_predictions", lambda: [])
    result = nfl_repository.get_nfl_calibration()
    assert result["sample_size"] == 0
    assert result["observed_accuracy"] is None
    assert result["accuracy_ci_95"] is None
    assert result["calibration"] == []
    assert result["calibration_ready"] is False
