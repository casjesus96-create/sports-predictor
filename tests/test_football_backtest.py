from football_backtest import run_chronological_backtest


def fixture(match_id, home, away, home_goals, away_goals, date, status="FINISHED"):
    return {
        "id": match_id,
        "status": status,
        "utcDate": date,
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "score": {"fullTime": {"home": home_goals, "away": away_goals}},
    }


def history_with_repeated_pair():
    scores = [(2, 0), (1, 1), (0, 1), (3, 1), (1, 0), (2, 2), (0, 2), (2, 1)]
    rows = []
    for i, (hg, ag) in enumerate(scores, start=1):
        home, away = ("Alpha", "Beta") if i % 2 else ("Beta", "Alpha")
        rows.append(fixture(
            i, home, away, hg, ag, f"2026-01-{i:02d}T15:00:00Z"
        ))
    return rows


def test_backtest_is_chronological_and_scores_both_models_on_same_sample():
    result = run_chronological_backtest(history_with_repeated_pair())
    assert result["evaluation_type"] == "chronological_walk_forward"
    assert result["read_only"] is True
    assert result["scored_matches"] > 0
    assert result["metrics"]["base"]["sample_size"] == result["scored_matches"]
    assert result["metrics"]["h2h_candidate"]["sample_size"] == result["scored_matches"]
    assert result["metrics"]["base"]["brier_score"] is not None
    assert result["metrics"]["base"]["log_loss"] is not None
    assert result["metrics"]["base"]["outcome_calibration"]
    assert result["metrics"]["h2h_candidate"]["reliability_bins"]
    diagnostics = result["h2h_diagnostics"]
    assert diagnostics["matches_with_probability_adjustment"] + diagnostics["matches_unchanged_from_base"] == result["scored_matches"]
    assert diagnostics["matches_using_external_provider_h2h"] == 0


def test_h2h_never_uses_the_target_or_later_matches():
    rows = history_with_repeated_pair()
    result = run_chronological_backtest(rows)
    by_id = {row["match_id"]: row for row in result["per_match"]}
    for match_id, scored in by_id.items():
        assert scored["h2h_valid_meetings"] <= match_id - 1
    assert all(row["match_id"] not in {None} for row in result["per_match"])


def test_unfinished_and_timezone_naive_targets_are_excluded():
    rows = history_with_repeated_pair()
    rows.append(fixture(20, "Alpha", "Beta", 0, 0, "2026-02-01T15:00:00Z", status="SCHEDULED"))
    rows.append(fixture(21, "Alpha", "Beta", 0, 0, "2026-02-02T15:00:00"))
    result = run_chronological_backtest(rows)
    assert result["excluded_invalid_or_unfinished_targets"] == 2
    assert result["scored_matches"] > 0


def test_empty_input_returns_insufficient_data_without_errors():
    result = run_chronological_backtest([])
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["scored_matches"] == 0
    assert result["metrics"]["base"]["brier_score"] is None
    assert result["metrics"]["h2h_candidate"]["log_loss"] is None
