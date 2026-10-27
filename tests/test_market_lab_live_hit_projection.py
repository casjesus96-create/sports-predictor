from batter_hit_projection import build_live_batter_hit_projections


def test_live_hit_projection_uses_season_avg_and_remaining_opportunities(monkeypatch):
    monkeypatch.setattr(
        "batter_hit_projection._fetch_season_hitting_stats",
        lambda player_ids, season: {
            101: {"season": season, "avg": 0.300, "at_bats": 100, "hits": 30},
            202: {"season": season, "avg": 0.250, "at_bats": 80, "hits": 20},
        },
    )
    result = build_live_batter_hit_projections(
        [
            {
                "side": "away",
                "team_name": "Away",
                "hitters": [
                    {"player_id": 101, "player_name": "Hitter With Hit", "batting_order": 1,
                     "hits_in_game": 1, "at_bats_in_game": 1},
                    {"player_id": 202, "player_name": "Hitter No Hit", "batting_order": 2,
                     "hits_in_game": 0, "at_bats_in_game": 1},
                ],
            }
        ],
        season=2026,
        current_inning=5,
        inning_state="Top",
        game_status="Live",
    )

    hitters = result["teams"][0]["hitters"]
    assert result["available"] is True
    assert result["status"] == "experimental"
    assert hitters[0]["probability_percent"] == 100.0
    assert "Ya consiguió" in hitters[0]["projection_note"]
    assert hitters[1]["probability_percent"] is not None
    assert 0 < hitters[1]["probability_percent"] < 100
    assert hitters[1]["expected_remaining_at_bats"] > 0


def test_live_hit_projection_reports_unavailable_when_stats_missing(monkeypatch):
    monkeypatch.setattr("batter_hit_projection._fetch_season_hitting_stats", lambda player_ids, season: {})
    result = build_live_batter_hit_projections(
        [{"side": "home", "team_name": "Home", "hitters": [
            {"player_id": 999, "player_name": "Unknown", "batting_order": 1,
             "hits_in_game": 0, "at_bats_in_game": 0}
        ]}],
        season=2026,
        current_inning=1,
        inning_state="Top",
        game_status="Warmup",
    )
    assert result["available"] is False
    assert result["teams"][0]["hitters"][0]["probability_percent"] is None
    assert result["teams"][0]["hitters"][0]["status"] == "unavailable"



def test_live_hit_projection_shrinks_pitcher_history_toward_season_average(monkeypatch):
    monkeypatch.setattr(
        "batter_hit_projection._fetch_season_hitting_stats",
        lambda player_ids, season: {
            101: {"season": season, "avg": 0.300, "at_bats": 100, "hits": 30},
        },
    )
    monkeypatch.setattr(
        "batter_hit_projection._fetch_vs_pitcher_stats",
        lambda player_ids, pitcher_id: {
            101: {
                "available": True,
                "avg": 0.500,
                "at_bats": 10,
                "hits": 5,
                "sample_size": 10,
            },
        },
    )
    result = build_live_batter_hit_projections(
        [{
            "side": "away",
            "team_name": "Away",
            "opposing_pitcher_id": 999,
            "opposing_pitcher_name": "Pitcher Example",
            "pitcher_source": "pitcher actual en juego",
            "hitters": [{
                "player_id": 101,
                "player_name": "Hitter Example",
                "batting_order": 1,
                "hits_in_game": 0,
                "at_bats_in_game": 0,
            }],
        }],
        season=2026,
        current_inning=1,
        inning_state="Top",
        game_status="Live",
    )
    hitter = result["teams"][0]["hitters"][0]
    assert hitter["vs_pitcher_avg"] == 0.5
    assert hitter["vs_pitcher_at_bats"] == 10
    assert 0.300 < hitter["adjusted_avg"] < 0.500
    assert hitter["pitcher_source"] == "pitcher actual en juego"
    baseline_percent = (1 - (1 - 0.300) ** 4.35) * 100
    assert baseline_percent < hitter["probability_percent"] < 100



def test_hit_already_achieved_keeps_100_percent_and_separates_next_hit(monkeypatch):
    monkeypatch.setattr(
        "batter_hit_projection._fetch_season_hitting_stats",
        lambda player_ids, season: {
            101: {"season": season, "avg": 0.291, "at_bats": 100, "hits": 29},
        },
    )
    monkeypatch.setattr(
        "batter_hit_projection._fetch_vs_pitcher_stats",
        lambda player_ids, pitcher_id: {
            101: {"available": True, "avg": 0.0, "at_bats": 4, "hits": 0, "sample_size": 4},
        },
    )
    result = build_live_batter_hit_projections(
        [{
            "side": "away",
            "team_name": "Brewers",
            "opposing_pitcher_id": 999,
            "opposing_pitcher_name": "Pitcher Example",
            "pitcher_source": "abridor previsto",
            "hitters": [{
                "player_id": 101, "player_name": "Hitter Example", "batting_order": 1,
                "hits_in_game": 1, "at_bats_in_game": 1,
            }],
        }],
        season=2026, current_inning=5, inning_state="Top", game_status="Live",
    )
    hitter = result["teams"][0]["hitters"][0]
    assert hitter["probability_percent"] == 100.0
    assert 0 < hitter["probability_additional_hit_percent"] < 100
    assert hitter["probability_additional_hit_percent"] < (
        (1 - (1 - 0.291) ** hitter["expected_remaining_at_bats"]) * 100
    )
    assert "otro hit" in hitter["projection_note"].lower()
