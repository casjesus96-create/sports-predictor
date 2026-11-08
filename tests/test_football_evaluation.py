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



def test_competition_calibration_reports_date_cluster_uncertainty_and_eligibility():
    from football_evaluation_api import _competition_calibration

    items = []
    for day in range(20):
        for match in range(3):
            actual = ("home", "draw", "away")[(day + match) % 3]
            probabilities = [0.50, 0.25, 0.25]
            items.append((
                {"kickoff_at": f"2026-01-{day + 1:02d}T12:00:00Z"},
                probabilities,
                actual,
                0,
            ))

    result = _competition_calibration(items, seed=77)
    assert result["sample_size"] == 60
    assert result["independent_dates"] == 20
    assert result["eligible_for_descriptive_comparison"] is True
    assert result["scope"] == "official_model_settled_snapshots_only"
    assert set(result["outcomes"]) == {"home", "draw", "away"}
    assert result["outcomes"]["home"]["bias_ci_95"] is not None
    assert result["outcomes"]["home"]["interpretation"] in {
        "SOBREESTIMACION", "SUBESTIMACION", "SIN_EVIDENCIA_CONCLUYENTE"
    }


def test_competition_calibration_marks_small_samples_and_missing_dates():
    from football_evaluation_api import _competition_calibration

    items = [
        ({"kickoff_at": None}, [0.5, 0.25, 0.25], "home", 0)
        for _ in range(60)
    ]
    result = _competition_calibration(items, seed=3)
    assert result["sample_size"] == 60
    assert result["independent_dates"] == 0
    assert result["eligible_for_descriptive_comparison"] is False
    assert result["outcomes"]["home"]["bias_ci_95"] is None
    assert result["outcomes"]["home"]["interpretation"] == "IC95_NO_ESTIMABLE"



def test_season_key_uses_july_to_june_boundaries():
    from football_evaluation_api import _season_key

    assert _season_key("2026-07-01T00:00:00Z") == "2026-27"
    assert _season_key("2026-11-08T12:00:00Z") == "2026-27"
    assert _season_key("2027-06-30T23:59:00Z") == "2026-27"
    assert _season_key("2027-07-01T00:00:00Z") == "2027-28"
    assert _season_key(None) is None
    assert _season_key("unknown") is None


def test_season_calibration_remains_descriptive_and_requires_independent_dates():
    from football_evaluation_api import _competition_calibration

    items = []
    for day in range(12):
        for match in range(5):
            items.append((
                {"kickoff_at": f"2026-08-{day + 1:02d}T12:00:00Z"},
                [0.50, 0.25, 0.25],
                ("home", "draw", "away")[(day + match) % 3],
                0,
            ))
    result = _competition_calibration(items, seed=2026)
    assert result["sample_size"] == 60
    assert result["independent_dates"] == 12
    assert result["eligible_for_descriptive_comparison"] is True
    assert result["scope"] == "official_model_settled_snapshots_only"


def test_season_metrics_use_home_draw_and_away_actual_indices():
    import math
    from football_evaluation_api import _season_metrics

    items = [
        ({"kickoff_at": "2026-08-01T12:00:00Z"}, [0.8, 0.1, 0.1], "home", 0),
        ({"kickoff_at": "2026-08-02T12:00:00Z"}, [0.1, 0.8, 0.1], "draw", 1),
        ({"kickoff_at": "2026-08-03T12:00:00Z"}, [0.1, 0.1, 0.8], "away", 2),
    ]

    metrics = _season_metrics(items)

    assert metrics["accuracy"] == 1.0
    assert metrics["brier_score"] == 0.06
    assert math.isclose(metrics["log_loss"], -math.log(0.8), abs_tol=1e-6)
