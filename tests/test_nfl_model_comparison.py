import nfl_repository


def _snapshot(version, event_id, home_probability, actual="BUF", status="SETTLED", created="2026-10-01T00:00:00Z"):
    return {
        "event_id": event_id,
        "model_version": version,
        "created_at": created,
        "result_status": status,
        "home_probability": home_probability,
        "away_probability": 1 - home_probability if home_probability is not None else None,
        "actual_winner": actual,
        "prediction_result": "PUSH" if actual == "TIE" else None,
        "features": {"game": {"home": "BUF", "away": "MIA"}},
    }


def test_model_comparison_reports_versions_and_paired_same_sample_metrics():
    rows = [
        _snapshot("NFL-1.0.0", "g1", 0.70, "BUF"),
        _snapshot("NFL-1.0.0", "g2", 0.60, "MIA"),
        _snapshot("NFL-ADVANCED-1", "g1", 0.55, "BUF"),
        _snapshot("NFL-ADVANCED-1", "g2", 0.40, "MIA"),
        _snapshot("NFL-ADVANCED-1", "g3", 0.80, "BUF"),
    ]

    result = nfl_repository.build_nfl_model_comparison(rows)

    assert result["success"] is True
    assert result["official_model_version"] == "NFL-1.0.0"
    models = {item["model_version"]: item for item in result["models"]}
    assert models["NFL-1.0.0"]["role"] == "official"
    assert models["NFL-1.0.0"]["evaluated"] == 2
    assert models["NFL-1.0.0"]["calibration"]
    assert models["NFL-ADVANCED-1"]["role"] == "experimental"
    assert models["NFL-ADVANCED-1"]["evaluated"] == 3

    paired = result["paired_comparisons"][0]
    assert paired["same_sample_size"] == 2
    assert paired["brier_improvement_a_minus_b"] is not None
    assert result["read_only"] is True
    assert result["model_impact"] == "none"


def test_model_comparison_excludes_pushes_invalid_rows_and_deduplicates_event_version():
    rows = [
        _snapshot("NFL-1.0.0", "g1", 0.7, "BUF"),
        _snapshot("NFL-1.0.0", "g1", 0.9, "BUF", created="2026-10-02T00:00:00Z"),
        _snapshot("NFL-1.0.0", "g2", 0.5, "TIE"),
        _snapshot("NFL-1.0.0", "g3", None, "BUF"),
        _snapshot("NFL-1.0.0", "g4", 0.6, "BUF", status="PENDING"),
    ]

    result = nfl_repository.build_nfl_model_comparison(rows)
    summary = result["models"][0]

    assert summary["snapshots"] == 3
    assert summary["pending"] == 1
    assert summary["pushes"] == 1
    assert summary["evaluated"] == 1
    assert summary["invalid_or_unverifiable"] == 1
    assert result["deduplicated_duplicate_snapshots"] == 1


def test_model_comparison_returns_empty_without_fabricating_metrics():
    result = nfl_repository.build_nfl_model_comparison([])

    assert result["models"] == []
    assert result["paired_comparisons"] == []
    assert result["read_only"] is True
