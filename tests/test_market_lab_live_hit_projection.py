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


def test_live_projection_note_reports_exact_hit_count_and_adjusted_probability(monkeypatch):
    monkeypatch.setattr("batter_hit_projection._fetch_season_hitting_stats", lambda player_ids, season: {
        101: {"season": season, "avg": 0.291, "at_bats": 100, "hits": 29},
    })
    monkeypatch.setattr("batter_hit_projection._fetch_vs_pitcher_stats", lambda player_ids, pitcher_id: {
        101: {"available": True, "avg": 0.0, "at_bats": 4, "hits": 0, "sample_size": 4},
    })
    result = build_live_batter_hit_projections(
        [{"side": "away", "team_name": "Brewers", "opposing_pitcher_id": 999,
          "opposing_pitcher_name": "Pitcher Example", "hitters": [{
              "player_id": 101, "player_name": "Hitter Example", "batting_order": 1,
              "hits_in_game": 2, "at_bats_in_game": 2,
          }]}],
        season=2026, current_inning=7, inning_state="Top", game_status="Live",
    )
    hitter = result["teams"][0]["hitters"][0]
    baseline = 1 - (1 - 0.291) ** hitter["expected_remaining_at_bats"]
    assert hitter["probability_percent"] == 100.0
    assert hitter["probability_additional_hit_percent"] < baseline * 100
    assert "2 hit(s)" in hitter["projection_note"]
    assert hitter["vs_pitcher_hits"] == 0



def test_unconfirmed_next_pitcher_ignores_stale_pitcher_id_and_explains_no_adjustment(monkeypatch):
    monkeypatch.setattr(
        "batter_hit_projection._fetch_season_hitting_stats",
        lambda player_ids, season: {
            101: {"season": season, "avg": 0.291, "at_bats": 100, "hits": 29},
        },
    )

    def unexpected_matchup_lookup(player_ids, pitcher_id):
        raise AssertionError("No debe consultarse historial con pitcher no confirmado")

    monkeypatch.setattr(
        "batter_hit_projection._fetch_vs_pitcher_stats",
        unexpected_matchup_lookup,
    )
    result = build_live_batter_hit_projections(
        [{
            "side": "away",
            "team_name": "Brewers",
            # Deliberately stale ID: the source status must take precedence.
            "opposing_pitcher_id": 999,
            "opposing_pitcher_name": "Stale Pitcher",
            "pitcher_source": "próximo pitcher no confirmado",
            "hitters": [{
                "player_id": 101,
                "player_name": "Hitter Example",
                "batting_order": 1,
                "hits_in_game": 4,
                "at_bats_in_game": 4,
            }],
        }],
        season=2026,
        current_inning=7,
        inning_state="Top",
        game_status="Live",
    )
    hitter = result["teams"][0]["hitters"][0]
    assert hitter["probability_percent"] == 100.0
    assert hitter["matchup_adjustment_applied"] is False
    assert hitter["vs_pitcher_avg"] is None
    assert hitter["opposing_pitcher_name"] is None
    assert "próximo pitcher no confirmado" in hitter["projection_note"].lower()
    assert "no se aplicó ajuste directo" in hitter["projection_note"].lower()
    assert "pitcher identificado solo se aplica" not in hitter["projection_note"].lower()

def test_extra_innings_do_not_force_remaining_hit_probability_to_zero(monkeypatch):
    monkeypatch.setattr(
        "batter_hit_projection._fetch_season_hitting_stats",
        lambda player_ids, season: {
            101: {"season": season, "avg": 0.300, "at_bats": 100, "hits": 30},
        },
    )
    monkeypatch.setattr(
        "batter_hit_projection._fetch_vs_pitcher_stats",
        lambda player_ids, pitcher_id: {},
    )
    result = build_live_batter_hit_projections(
        [{
            "side": "away",
            "team_name": "Away",
            "hitters": [{
                "player_id": 101,
                "player_name": "Hitter Example",
                "batting_order": 1,
                "hits_in_game": 0,
                "at_bats_in_game": 4,
            }],
        }],
        season=2026,
        current_inning=10,
        inning_state="Top",
        game_status="Live",
    )
    hitter = result["teams"][0]["hitters"][0]
    assert result["remaining_opportunities_method"] == "solo_entrada_extra_actual"
    assert result["remaining_game_fraction"] > 0
    assert hitter["expected_remaining_at_bats"] > 0
    assert hitter["probability_percent"] > 0
    assert "no predice cuántas entradas extra habrá después" in result["note"].lower()

