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
    assert result["external_h2h_comparison"]["queried_sample_size"] == 0
    assert result["external_h2h_comparison"]["eligible_sample"]["sample_size"] == 0


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


def test_backtest_can_score_latest_target_window_using_full_training_history(monkeypatch):
    import football_backtest

    rows = history_with_repeated_pair()
    observed_history_sizes = []

    def fake_predict(home, away, history):
        observed_history_sizes.append(len(history))
        return {"available": True, "probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2}}

    def fake_h2h(home, away, kickoff, base, history):
        return {
            "available": True,
            "candidate_probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2},
            "h2h": {"valid_meetings": 0},
            "status": "INSUFFICIENT_H2H",
        }

    monkeypatch.setattr(football_backtest, "predict_1x2", fake_predict)
    monkeypatch.setattr(football_backtest, "evaluate_h2h_candidate", fake_h2h)
    monkeypatch.setattr(football_backtest, "predict_advanced_shadow", lambda *_args: {"available": False})

    result = run_chronological_backtest(rows, target_limit=2)

    assert result["input_matches"] == 8
    assert result["eligible_finished_matches"] == 8
    assert result["target_sample_size"] == 2
    assert result["scored_matches"] == 2
    assert observed_history_sizes == [6, 7]


def test_backtest_target_limit_must_be_positive():
    import pytest

    with pytest.raises(ValueError):
        run_chronological_backtest(history_with_repeated_pair(), target_limit=0)



def test_backtest_keeps_paired_goal_market_probabilities_and_actuals(monkeypatch):
    import football_backtest

    rows = []
    for i in range(1, 13):
        rows.append(fixture(i, "Alpha" if i % 2 else "Beta", "Beta" if i % 2 else "Alpha",
                            2 if i % 3 else 0, 1 if i % 4 else 0,
                            f"2026-01-{i:02d}T15:00:00Z"))

    base_markets = {
        "both_teams_to_score": {"yes": {"probability": 0.55}},
        "total_goals": {
            "over_1_5": {"probability": 0.70},
            "over_2_5": {"probability": 0.50},
            "over_3_5": {"probability": 0.30},
        },
    }

    def fake_predict(home, away, history):
        return {
            "available": True,
            "probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
            "goal_markets": base_markets,
            "expected_goals": {"home": 1.5, "away": 1.0, "total": 2.5},
        }

    def fake_h2h(home, away, kickoff, base, history):
        return {
            "available": True,
            "candidate_probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
            "h2h": {"valid_meetings": 0},
            "status": "INSUFFICIENT_H2H",
        }

    def fake_shadow(home, away, history, kickoff):
        return {
            "available": True,
            "probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
            "goal_markets": {
                "both_teams_to_score": {"yes": 0.60, "no": 0.40},
                "total_goals": {"over_1_5": 0.75, "over_2_5": 0.55, "over_3_5": 0.35},
            },
            "expected_goals": {"home": 1.7, "away": 1.1, "total": 2.8},
        }

    monkeypatch.setattr(football_backtest, "predict_1x2", fake_predict)
    monkeypatch.setattr(football_backtest, "evaluate_h2h_candidate", fake_h2h)
    monkeypatch.setattr(football_backtest, "predict_advanced_shadow", fake_shadow)

    result = run_chronological_backtest(rows)
    assert result["goal_market_sample_size"] == result["scored_matches"]
    assert len(result["goal_market_per_match"]) == result["scored_matches"]
    first = result["goal_market_per_match"][0]
    assert first["markets"]["btts_yes"]["base"] == 0.55
    assert first["markets"]["btts_yes"]["candidate"] == 0.60
    assert first["markets"]["over_2_5"]["actual"] is True
    assert first["base_expected_goals"]["total"] == 2.5
    assert first["candidate_expected_goals"]["total"] == 2.8
