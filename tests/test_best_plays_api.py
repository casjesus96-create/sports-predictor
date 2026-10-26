from best_plays_api import _eligible_snapshot, _market_quote, _normalize, _ranking_score


def _snapshot(model="NBA-1.1.0", sport="NBA", quality=85):
    return {
        "id": "snap-1", "event_id": "game-1", "sport": "basketball",
        "league": sport, "model_version": model, "created_at": "2026-10-25T12:00:00+00:00",
        "result_status": "PENDING", "home_probability": 0.62, "away_probability": 0.38,
        "data_quality": quality, "features": {"game": {"home": "Boston Celtics", "away": "Miami Heat"}},
    }


def test_only_official_model_snapshots_are_eligible():
    assert _eligible_snapshot(_snapshot())["sport"] == "NBA"
    assert _eligible_snapshot(_snapshot(model="NBA-experimental")) is None
    assert _eligible_snapshot(_snapshot(sport="TENNIS", model="TENNIS-ELO-1.0.0")) is None


def test_invalid_or_inconsistent_probabilities_are_rejected():
    row = _snapshot()
    row["away_probability"] = 0.30
    assert _eligible_snapshot(row) is None
    row = _snapshot()
    row["home_probability"] = None
    assert _eligible_snapshot(row) is None


def test_ranking_requires_real_quality_value():
    assert _ranking_score(8.0, 0.62, 85) is not None
    assert _ranking_score(8.0, 0.62, None) is None


def test_odds_match_requires_exact_normalized_team_name():
    event = {"home_team": "Boston Celtics", "away_team": "Miami Heat", "bookmakers": [
        {"title": "Book A", "markets": [{"key": "h2h", "last_update": "2026-10-25T10:00:00Z",
          "outcomes": [{"name": "Boston Celtics", "price": 1.8}, {"name": "Miami Heat", "price": 2.1}]}]}
    ]}
    assert _normalize("Boston Celtics") == _normalize("Boston Celtics")
    assert _market_quote(event, "Boston Celtics")["decimal_odds"] == 1.8
    assert _market_quote(event, "Boston Celtics")["opponent_decimal_odds"] == 2.1


def test_odds_missing_does_not_create_quote():
    event = {"home_team": "Boston Celtics", "away_team": "Miami Heat", "bookmakers": []}
    assert _market_quote(event, "Boston Celtics") is None
