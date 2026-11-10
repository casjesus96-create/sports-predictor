from nba_score_evaluation import evaluate_score_projections


def _row(event_id, created_at, home, away, actual_home, actual_away):
    return {
        "event_id": event_id,
        "created_at": created_at,
        "result_status": "SETTLED",
        "actual_home_score": actual_home,
        "actual_away_score": actual_away,
        "features": {"projections": {"home_points": home, "away_points": away}},
    }


def test_evaluates_team_and_total_errors_with_signed_bias():
    result = evaluate_score_projections([
        _row("game-1", "2026-11-01", 100, 110, 105, 108),
    ])

    assert result["sample_games"] == 1
    assert result["team_score_observations"] == 2
    assert result["team_points_mae"] == 3.5
    assert result["team_points_bias"] == 1.5
    assert result["game_total_mae"] == 3.0
    assert result["game_total_bias"] == 3.0
    assert result["team_points_within_5_pct"] == 100.0
    assert result["game_total_within_5_pct"] == 100.0


def test_uses_only_latest_settled_snapshot_per_game():
    older = _row("game-1", "2026-11-01", 90, 100, 105, 108)
    newer = _row("game-1", "2026-11-02", 100, 110, 105, 108)

    result = evaluate_score_projections([older, newer])

    assert result["sample_games"] == 1
    assert result["team_points_mae"] == 1.5
    assert result["game_total_mae"] == 3.0


def test_skips_pending_missing_and_non_finite_projections():
    pending = _row("pending", "2026-11-01", 100, 110, 105, 108)
    pending["result_status"] = "PENDING"
    missing = _row("missing", "2026-11-02", None, 110, 105, 108)
    invalid = _row("invalid", "2026-11-03", float("nan"), 110, 105, 108)

    result = evaluate_score_projections([pending, missing, invalid])

    assert result["sample_games"] == 0
    assert result["skipped_without_valid_projection"] == 2
    assert result["team_points_mae"] is None
    assert result["game_total_mae"] is None


def test_empty_sample_returns_safe_null_metrics():
    result = evaluate_score_projections([])

    assert result["sample_games"] == 0
    assert result["team_points_rmse"] is None
    assert result["game_total_within_10_pct"] is None
