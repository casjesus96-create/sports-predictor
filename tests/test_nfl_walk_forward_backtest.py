import nfl_walk_forward_backtest as backtest


def test_team_features_excludes_same_kickoff_and_future_games():
    games = [
        {"game_id": "g1", "season": 2026, "kickoff": "2026-09-01T17:00:00+00:00",
         "game_type": "REG", "home": "BUF", "away": "MIA", "home_score": 20, "away_score": 10},
        {"game_id": "g2", "season": 2026, "kickoff": "2026-09-08T17:00:00+00:00",
         "game_type": "REG", "home": "BUF", "away": "NYJ", "home_score": 24, "away_score": 17},
        {"game_id": "g3", "season": 2026, "kickoff": "2026-09-15T17:00:00+00:00",
         "game_type": "REG", "home": "MIA", "away": "BUF", "home_score": None, "away_score": None},
    ]
    metrics = {
        ("BUF", "g1"): {"passing_epa": 2.0, "point_diff": 10.0},
        ("BUF", "g2"): {"passing_epa": 1000.0, "point_diff": 7.0},
    }
    values, count = backtest._team_features(
        "BUF", backtest._time(games[1]["kickoff"]), games, metrics
    )
    assert count == 1
    assert values[0] == 2.0
    assert values[-1] == 10.0


def test_logistic_fit_predict_is_finite_and_deterministic():
    training = [
        ([-2.0, 0.0], 0),
        ([-1.0, 1.0], 0),
        ([1.0, -1.0], 1),
        ([2.0, 0.0], 1),
    ]
    model = backtest._fit_logistic(training, 2)
    p1 = backtest._predict_logistic(model, [1.5, 0.0])
    p2 = backtest._predict_logistic(model, [1.5, 0.0])
    assert 0.0 < p1 < 1.0
    assert p1 == p2
    assert p1 > 0.5


def test_score_reports_brier_log_loss_and_accuracy():
    result = backtest._score([0.8, 0.2], [1, 0])
    assert result["sample_size"] == 2
    assert result["accuracy_pct"] == 100.0
    assert result["brier_score"] == 0.04
    assert result["log_loss"] > 0
    assert result["calibration"]
