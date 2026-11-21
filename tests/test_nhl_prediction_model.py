import pytest

from nhl_prediction_model import build_elo_ratings, predict_winner


def _game(game_id, day, home="TOR", away="BOS", home_score=3, away_score=2, game_type=2):
    return {
        "game_id": str(game_id), "game_date": day,
        "home_team_canonical_key": home, "away_team_canonical_key": away,
        "home_score": home_score, "away_score": away_score,
        "game_type": game_type, "result_status": "FINAL", "training_eligible": True,
    }


def test_elo_uses_only_eligible_completed_games_before_cutoff():
    rows = [
        _game("1", "2025-10-01"),
        _game("2", "2025-10-02", home="BOS", away="TOR", home_score=1, away_score=4),
        _game("3", "2025-10-03", home="TOR", away="BOS", home_score=9, away_score=1),
        {**_game("4", "2025-10-01"), "training_eligible": False},
    ]
    model = build_elo_ratings(rows, as_of_date="2025-10-03")
    assert model["games_used"] == 2
    assert model["games_played_by_team"] == {"TOR": 2, "BOS": 2}
    assert model["source"] == "own_approved_historical_archive_only"


def test_regular_season_and_playoffs_are_separated():
    rows = [_game("1", "2025-10-01", game_type=2), _game("2", "2026-04-20", game_type=3)]
    assert build_elo_ratings(rows, game_type=2)["games_used"] == 1
    assert build_elo_ratings(rows, game_type=3)["games_used"] == 1


def test_empty_archive_returns_no_fake_percentage():
    result = predict_winner([], "TOR", "BOS", as_of_date="2026-11-21")
    assert result["status"] == "INSUFFICIENT_HISTORICAL_SAMPLE"
    assert result["probabilities"] is None


def test_prediction_publishes_complementary_probabilities_after_sample_gate():
    rows = [_game(str(i), f"2025-10-{i + 1:02d}") for i in range(30)]
    result = predict_winner(rows, "TOR", "BOS", as_of_date="2026-11-21", min_games=30, min_team_games=5)
    assert result["status"] == "RESEARCH_PROJECTION"
    assert result["probabilities"]["home_win"] + result["probabilities"]["away_win"] == pytest.approx(100)
    assert result["historical_games_used"] == 30


def test_prediction_rejects_same_team_and_invalid_game_type():
    with pytest.raises(ValueError, match="diferentes"):
        predict_winner([], "TOR", "TOR", as_of_date="2026-11-21")
    with pytest.raises(ValueError, match="game_type"):
        build_elo_ratings([], game_type=1)


def test_conflicting_duplicate_game_ids_are_rejected():
    rows = [_game("same", "2025-10-01"), _game("same", "2025-10-01", home_score=4)]
    with pytest.raises(ValueError, match="contradictorio"):
        build_elo_ratings(rows)
