from nba_calibration import build_confidence_calibration, wilson_interval


def test_wilson_interval_matches_known_one_of_three_sample():
    assert wilson_interval(1, 3) == {"lower": 0.0615, "upper": 0.7923}


def test_confidence_calibration_groups_favorites_and_reports_uncertainty():
    rows = [
        {"confidence": 0.52, "correct": True},
        {"confidence": 0.54, "correct": False},
        {"confidence": 0.63, "correct": True},
        {"confidence": 0.91, "correct": True},
    ]
    result = build_confidence_calibration(rows)
    assert result["sample_size"] == 4
    assert result["observed_accuracy"] == 0.75
    assert result["accuracy_ci_95"] == wilson_interval(3, 4)
    assert [item["range"] for item in result["bins"]] == ["50%-55%", "60%-65%", "90%-95%"]
    assert all(item["small_sample"] for item in result["bins"])
    assert result["read_only"] is True
    assert result["official_probability_changed"] is False


def test_confidence_calibration_excludes_invalid_probabilities_and_handles_empty_sample():
    result = build_confidence_calibration([
        {"confidence": 0.49, "correct": True},
        {"confidence": 0.99, "correct": False},
        {"confidence": float("nan"), "correct": True},
        {"confidence": "bad", "correct": True},
    ])
    assert result["sample_size"] == 0
    assert result["observed_accuracy"] is None
    assert result["accuracy_ci_95"] is None
    assert result["bins"] == []
    assert result["calibration_ready"] is False


def test_confidence_calibration_marks_minimum_sample_without_changing_model():
    rows = [{"confidence": 0.7, "correct": index % 2 == 0} for index in range(30)]
    result = build_confidence_calibration(rows)
    assert result["calibration_ready"] is True
    assert result["sample_size"] == 30
    assert result["official_probability_changed"] is False



def test_temporal_calibration_uses_two_chronological_date_clustered_windows():
    from nba_calibration import build_temporal_calibration_stability

    rows = []
    for day in range(1, 5):
        for game in range(20):
            rows.append({
                "kickoff": f"2026-10-{day:02d}T23:{game % 60:02d}:00Z",
                "confidence": 0.80 if day <= 2 else 0.60,
                "correct": day > 2,
            })

    result = build_temporal_calibration_stability(rows)

    assert result["eligible"] is True
    assert result["sample_size"] == 80
    assert result["split_before"] == "2026-10-03"
    assert [window["sample_size"] for window in result["windows"]] == [40, 40]
    assert result["windows"][0]["end_date"] == "2026-10-02"
    assert result["windows"][1]["start_date"] == "2026-10-03"
    assert result["windows"][0]["calibration_error"] < 0
    assert result["windows"][1]["calibration_error"] > 0
    assert all(window["accuracy_ci_95"] is not None for window in result["windows"])
    assert result["read_only"] is True
    assert result["official_probability_changed"] is False


def test_temporal_calibration_reports_insufficient_sample_and_exclusions():
    from nba_calibration import build_temporal_calibration_stability

    rows = [
        {"kickoff": "2026-10-01T19:00:00Z", "confidence": 0.7, "correct": True}
        for _ in range(29)
    ]
    rows.extend([
        {"confidence": 0.8, "correct": False},
        {"kickoff": "not-a-date", "confidence": 0.8, "correct": False},
    ])

    result = build_temporal_calibration_stability(rows)

    assert result["eligible"] is False
    assert result["windows"] == []
    assert result["sample_size"] == 29
    assert result["excluded_missing_kickoff"] == 1
    assert result["excluded_invalid_observation"] == 1
    assert result["minimum_per_window"] == 30
