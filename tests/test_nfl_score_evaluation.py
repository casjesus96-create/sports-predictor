from datetime import datetime, timezone

from nfl_score_evaluation import _projections, _stats_before, _summary


def test_stats_before_excludes_games_at_or_after_cutoff():
    cutoff = datetime(2026, 10, 1, tzinfo=timezone.utc)
    games = [
        {"game_type": "REG", "game_id": "old", "kickoff": "2026-09-01T00:00:00Z",
         "home": "MIA", "away": "NYJ", "home_score": 28, "away_score": 20},
        {"game_type": "REG", "game_id": "same", "kickoff": "2026-10-01T00:00:00Z",
         "home": "MIA", "away": "BUF", "home_score": 7, "away_score": 35},
        {"game_type": "REG", "game_id": "future", "kickoff": "2026-10-02T00:00:00Z",
         "home": "NE", "away": "MIA", "home_score": 3, "away_score": 40},
    ]
    stats = _stats_before("MIA", cutoff, games)
    assert stats["games"] == 1
    assert stats["points_for"] == 28
    assert stats["points_against"] == 20


def test_enriched_projection_is_available_and_bounded():
    history = [
        {"game_type": "REG", "game_id": "1", "kickoff": "2026-09-01T00:00:00Z",
         "home": "MIA", "away": "NYJ", "home_score": 28, "away_score": 20},
        {"game_type": "REG", "game_id": "2", "kickoff": "2026-09-08T00:00:00Z",
         "home": "BUF", "away": "MIA", "home_score": 17, "away_score": 24},
        {"game_type": "REG", "game_id": "3", "kickoff": "2026-09-15T00:00:00Z",
         "home": "NYJ", "away": "BUF", "home_score": 14, "away_score": 21},
    ]
    target = {"game_id": "target", "season": 2026, "game_type": "REG",
              "kickoff": "2026-09-22T00:00:00Z", "home": "MIA", "away": "BUF"}
    result = _projections(target, history)
    assert result is not None
    for version in ("baseline", "enriched"):
        home, away = result[version]
        assert 0 <= home <= 50
        assert 0 <= away <= 50


def test_summary_returns_margin_and_total_mae():
    rows = [
        {"pred_margin": 3, "actual_margin": 5, "pred_total": 40, "actual_total": 44},
        {"pred_margin": -1, "actual_margin": 1, "pred_total": 50, "actual_total": 48},
    ]
    result = _summary(rows)
    assert result["sample_size"] == 2
    assert result["margin_mae"] == 2.0
    assert result["total_mae"] == 3.0
