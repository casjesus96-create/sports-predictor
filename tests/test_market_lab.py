from market_lab_engine import catalog_for, poisson_at_least, poisson_margin_probability, project_snapshot

def test_catalog_has_sport_specific_markets():
    catalog = catalog_for()["sports"]
    assert {"MLB", "NBA", "NFL", "TENNIS", "FOOTBALL"} <= set(catalog)
    assert any(m["market_id"] == "batter_hits" for m in catalog["MLB"])
    assert any(m["market_id"] == "player_rebounds" for m in catalog["NBA"])

def test_poisson_probabilities_are_bounded():
    assert 0 <= poisson_at_least(6, 5.5) <= 1
    assert 0 <= poisson_margin_probability(5.0, 3.0, 2) <= 1

def test_projection_uses_saved_winner_probability_without_odds():
    row = {"id":"snap-1","event_id":"game-1","sport":"baseball","league":"MLB",
      "home_probability":0.6,"away_probability":0.4,"data_quality":90,
      "features":{"game":{"home":"Milwaukee","away":"Cubs"},"factors":{"run_projection":{
        "available":True,"home":{"expected_runs":5.0},"away":{"expected_runs":3.0}}}}}
    markets = project_snapshot(row)["markets"]
    assert markets[0]["probability"] == 0.6
    assert any(m["market_id"] == "runs_over_6" and m["probability"] is not None for m in markets)
    assert any(m["market_id"] == "batter_hit" and m["status"] == "unavailable" for m in markets)

def test_missing_projection_is_not_fabricated():
    row = {"id":"s","sport":"NFL","league":"NFL","home_probability":0.7,"away_probability":0.3,
      "features":{"game":{"home":"A","away":"B"},"factors":{"score_projection":{"available":False,"reason":"faltan datos"}}}}
    markets = project_snapshot(row)["markets"]
    points = next(m for m in markets if m["market_id"] == "projected_points")
    assert points["status"] == "unavailable" and points["value"] is None

def test_confirmed_batter_hit_projection_is_displayed_in_market_lab():
    row = {
        "id": "snap-hit", "sport": "MLB", "league": "MLB",
        "home_probability": 0.55, "away_probability": 0.45,
        "features": {"game": {"home": "Milwaukee", "away": "Miami"},
            "factors": {"batter_hit_projections": {"available": True, "status": "experimental",
                "note": "Estimación experimental.", "teams": [{"side": "home", "team_name": "Milwaukee",
                    "lineup_confirmed": True, "hitters": [{"player_id": 123, "player_name": "Christian Example",
                        "lineup_confirmed": True, "batting_order": 2, "season_avg": 0.28,
                        "season_at_bats": 300, "expected_at_bats": 4.25,
                        "probability_1plus_hit": 0.72}]}]}}}
    }
    markets = project_snapshot(row)["markets"]
    hit = next(m for m in markets if m["market_id"] == "batter_hit_123")
    assert hit["probability_percent"] == 72.0
    assert hit["status"] == "experimental"
