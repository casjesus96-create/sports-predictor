from datetime import date

import pytest

from tennis_history import (
    _aggregate_service_stats,
    get_player_profile,
    normalize_player_name,
    parse_cutoff,
)


@pytest.fixture(autouse=True)
def disable_persistent_archive_by_default(monkeypatch):
    monkeypatch.setattr("tennis_history.get_player_archive_profile", lambda **kwargs: None)


def test_archive_form_is_primary_and_legacy_stats_remain_provenance_only(monkeypatch):
    archived = {
        "success": True,
        "league": "ATP",
        "player_name": "Player One",
        "matches_in_window": 1,
        "wins_in_window": 1,
        "losses_in_window": 0,
        "win_rate": 1.0,
        "last_5": {"matches": 1, "wins": 1, "losses": 0, "win_rate": 1.0},
        "last_10": {"matches": 1, "wins": 1, "losses": 0, "win_rate": 1.0},
        "recent_matches": [{"date": "2026-11-17", "date_precision": "exact_match_date", "opponent": "Player Two", "result": "W"}],
        "surface_window": {"matches": 1, "wins": 1, "losses": 0, "win_rate": 1.0},
        "ranking_latest_in_window": 8,
        "days_since_last_match": 1,
        "workload_matches_last_7_days": 1,
        "workload_matches_last_14_days": 1,
        "data_quality": {
            "source": "Valuebetennis ATP/WTA historical match CSV",
            "latest_match_date_in_source": "2026-11-17",
            "source_data_age_days": 1,
            "source_freshness_status": "current",
            "source_freshness_thresholds_days": {"current_max": 45, "delayed_max": 90},
            "matches_with_service_stats": 0,
        },
    }
    legacy_rows = ({
        "tourney_date": "20260525",
        "winner_name": "Player One",
        "loser_name": "Player Two",
        "surface": "Clay",
        "winner_rank": "14",
        "score": "6-4 6-2",
        "w_svpt": "50",
        "w_ace": "5",
        "w_df": "1",
        "w_1stIn": "30",
        "w_1stWon": "22",
        "w_2ndWon": "10",
        "w_bpSaved": "2",
        "w_bpFaced": "3",
    },)
    monkeypatch.setattr("tennis_history.get_player_archive_profile", lambda **kwargs: archived)
    monkeypatch.setattr("tennis_history.load_year", lambda league, year: legacy_rows if year == 2026 else ())

    profile = get_player_profile("Player One", "ATP", "2026-11-18", lookback_days=365)

    assert profile["recent_matches"][0]["date"] == "2026-11-17"
    assert profile["recent_matches"][0]["date_precision"] == "exact_match_date"
    assert profile["days_since_last_match"] == 1
    assert profile["service_return_stats_last_10_matches"]["matches_with_service_stats"] == 0
    assert profile["service_return_stats_last_10_matches"]["aces_total"] is None
    assert profile["data_quality"]["legacy_service_stats"]["matches_with_service_stats"] == 1
    assert profile["data_quality"]["legacy_service_stats"]["aces_total"] == 5
    assert profile["ranking_latest_in_window"] is None
    assert profile["data_quality"]["legacy_ranking_latest_in_window"] == 14
    assert profile["data_quality"]["source_data_age_days"] == 1
    assert profile["data_quality"]["legacy_service_stats_latest_match_date"] == "2026-05-25"
    assert profile["data_quality"]["legacy_service_stats_age_days"] == 177


def test_ambiguous_exact_archive_identity_never_falls_back_to_legacy(monkeypatch):
    monkeypatch.setattr(
        "tennis_history.get_player_archive_profile",
        lambda **kwargs: {"identity_ambiguous": True},
    )
    monkeypatch.setattr(
        "tennis_history.load_year",
        lambda *args: (_ for _ in ()).throw(AssertionError("legacy fallback must not run")),
    )

    with pytest.raises(ValueError, match="Identidad ambigua"):
        get_player_profile("Player One", "ATP", "2026-11-18", lookback_days=365)


def test_archive_profile_survives_legacy_source_failure(monkeypatch):
    archived = {
        "success": True,
        "recent_matches": [{"date": "2026-11-17", "date_precision": "exact_match_date"}],
    }
    monkeypatch.setattr("tennis_history.get_player_archive_profile", lambda **kwargs: archived)
    monkeypatch.setattr(
        "tennis_history.load_year",
        lambda *args: (_ for _ in ()).throw(RuntimeError("legacy unavailable")),
    )

    profile = get_player_profile("Player One", "ATP", "2026-11-18", lookback_days=365)

    assert profile is archived
    assert profile["recent_matches"][0]["date_precision"] == "exact_match_date"


def test_normalize_player_name_ignores_accents_and_punctuation():
    assert normalize_player_name("João Fonseca") == "joao fonseca"
    assert normalize_player_name("  O'Connell, Chris ") == "o connell chris"


def test_parse_cutoff_validates_iso_date():
    assert parse_cutoff("2026-10-15") == date(2026, 10, 15)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_cutoff("15/10/2026")


def test_service_stats_use_only_available_denominators():
    stats = _aggregate_service_stats([
        ({"w_ace": "3", "w_df": "1", "w_svpt": "50", "w_1stIn": "30",
          "w_1stWon": "24", "w_2ndWon": "12", "w_bpSaved": "2", "w_bpFaced": "4"}, "winner"),
        ({"l_ace": "1", "l_df": "2", "l_svpt": "40", "l_1stIn": "20",
          "l_1stWon": "12", "l_2ndWon": "8", "l_bpSaved": "1", "l_bpFaced": "3"}, "loser"),
    ])
    assert stats["matches_with_service_stats"] == 2
    assert stats["aces_total"] == 4
    assert stats["double_faults_total"] == 3
    assert stats["first_serve_in_pct"] == 0.5556
    assert stats["first_serve_points_won_pct"] == 0.72
    assert stats["second_serve_points_won_pct"] == 0.5
    assert stats["break_points_saved_pct"] == 0.4286


def test_service_averages_exclude_matches_without_service_points():
    stats = _aggregate_service_stats([
        ({"w_ace": "3", "w_df": "1", "w_svpt": "50", "w_1stIn": "30",
          "w_1stWon": "24", "w_2ndWon": "12", "w_bpSaved": "2", "w_bpFaced": "4"}, "winner"),
        ({"l_ace": "8", "l_df": "5"}, "loser"),
    ])
    assert stats["matches_with_service_stats"] == 1
    assert stats["aces_total"] == 3
    assert stats["aces_per_match"] == 3.0
    assert stats["double_faults_per_match"] == 1.0


def test_profile_filters_out_matches_on_or_after_cutoff(monkeypatch):
    rows = (
        {"tourney_date": "20261001", "winner_name": "Player One", "loser_name": "Player Two",
         "surface": "Hard", "winner_rank": "10", "w_svpt": "50", "w_ace": "5",
         "w_df": "1", "w_1stIn": "30", "w_1stWon": "22", "w_2ndWon": "10",
         "w_bpSaved": "2", "w_bpFaced": "3", "minutes": "90"},
        {"tourney_date": "20261010", "winner_name": "Player Three", "loser_name": "Player One",
         "surface": "Clay", "loser_rank": "11", "l_svpt": "45", "l_ace": "2",
         "l_df": "3", "l_1stIn": "25", "l_1stWon": "15", "l_2ndWon": "8",
         "l_bpSaved": "1", "l_bpFaced": "4", "minutes": "100"},
        {"tourney_date": "20261015", "winner_name": "Player One", "loser_name": "Player Four",
         "surface": "Hard", "winner_rank": "9"},
    )

    monkeypatch.setattr("tennis_history.load_year", lambda league, year: rows if year == 2026 else ())
    profile = get_player_profile("Player One", "ATP", "2026-10-15", surface="Hard", lookback_days=365)
    assert profile["matches_in_window"] == 2
    assert profile["wins_in_window"] == 1
    assert profile["losses_in_window"] == 1
    assert profile["last_5"]["matches"] == 2
    assert profile["surface_window"]["matches"] == 1
    assert profile["surface_window"]["win_rate"] == 1.0
    assert profile["days_since_last_match"] == 5
    assert profile["data_quality"]["latest_match_date_in_source"] == "2026-10-10"
    assert profile["data_quality"]["source_data_age_days"] == 5
    assert profile["data_quality"]["source_freshness_status"] == "current"
    assert profile["ranking_latest_in_window"] == 11
    assert profile["data_quality"]["matches_with_service_stats"] == 2
    assert [item["date"] for item in profile["recent_matches"]] == ["2026-10-10", "2026-10-01"]
    assert profile["recent_matches"][0]["opponent"] == "Player Three"
    assert profile["recent_matches"][0]["result"] == "L"
    assert profile["recent_matches"][1]["score"] is None
    assert profile["recent_matches"][0]["date_precision"] == "tournament_start_date"
    assert profile["recent_matches"][0]["is_walkover"] is False



def test_walkover_counts_for_result_but_not_service_statistics(monkeypatch):
    rows = (
        {
            "tourney_date": "20260525",
            "winner_name": "Player One",
            "loser_name": "Player Two",
            "surface": "Clay",
            "score": "W/O",
        },
        {
            "tourney_date": "20260520",
            "winner_name": "Player Three",
            "loser_name": "Player One",
            "surface": "Clay",
            "score": "6-4 6-3",
            "l_ace": "2",
            "l_df": "1",
            "l_svpt": "40",
            "l_1stIn": "25",
            "l_1stWon": "15",
            "l_2ndWon": "8",
            "l_bpSaved": "1",
            "l_bpFaced": "3",
        },
    )
    monkeypatch.setattr("tennis_history.load_year", lambda league, year: rows if year == 2026 else ())

    profile = get_player_profile("Player One", "ATP", "2026-06-01", lookback_days=365)

    assert profile["matches_in_window"] == 2
    assert profile["wins_in_window"] == 1
    assert profile["losses_in_window"] == 1
    assert profile["data_quality"]["matches_with_service_stats"] == 1
    assert profile["service_return_stats_last_10_matches"]["matches_with_service_stats"] == 1
    walkover = next(item for item in profile["recent_matches"] if item["is_walkover"])
    assert walkover["result"] == "W"
    assert walkover["score"] == "W/O"


def test_profile_reports_stale_source_separately_from_player_inactivity(monkeypatch):
    rows = (
        {"tourney_date": "20260525", "winner_name": "Player One", "loser_name": "Player Two", "surface": "Clay"},
        {"tourney_date": "20260520", "winner_name": "Player Three", "loser_name": "Player One", "surface": "Clay"},
    )
    monkeypatch.setattr("tennis_history.load_year", lambda league, year: rows if year == 2026 else ())

    profile = get_player_profile("Player One", "ATP", "2026-11-18", lookback_days=365)

    assert profile["days_since_last_match"] == 177
    assert profile["data_quality"]["latest_match_date_in_source"] == "2026-05-25"
    assert profile["data_quality"]["source_data_age_days"] == 177
    assert profile["data_quality"]["source_freshness_status"] == "stale"
    assert "cobertura histórica está desactualizada" in profile["data_quality"]["warning"]


def test_profile_rejects_invalid_surface_and_league():
    with pytest.raises(ValueError, match="surface"):
        get_player_profile("Player One", "ATP", "2026-10-15", surface="Synthetic")
    with pytest.raises(ValueError, match="ATP o WTA"):
        get_player_profile("Player One", "ITF", "2026-10-15")



def test_load_year_uses_archive_mirror_and_parses_annual_csv(monkeypatch):
    import tennis_history

    captured = {}

    class FakeResponse:
        status_code = 200
        text = (
            "tourney_date,winner_name,loser_name,surface,score\n"
            "20250106,Player One,Player Two,Hard,6-4 6-3\n"
        )

        def raise_for_status(self):
            return None

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(tennis_history.requests, "get", fake_get)
    tennis_history.load_year.cache_clear()
    rows = tennis_history.load_year("ATP", 2025)

    assert captured["url"] == (
        "https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/"
        "main/atp/atp_matches_2025.csv"
    )
    assert captured["timeout"] == tennis_history.TIMEOUT_SECONDS
    assert len(rows) == 1
    assert rows[0]["winner_name"] == "Player One"


def test_backtest_fails_clearly_when_no_historical_files_load(monkeypatch):
    from tennis_backtest import run_elo_backtest
    from tennis_history import HistoricalDataError

    monkeypatch.setattr("tennis_backtest.load_year", lambda league, year: ())
    with pytest.raises(HistoricalDataError, match="No se cargaron datos históricos ATP"):
        run_elo_backtest(
            league="ATP",
            start_date="2025-10-01",
            end_date="2025-10-02",
            warmup_years=1,
        )



def test_partial_service_fields_use_metric_specific_sample_denominators():
    stats = _aggregate_service_stats([
        ({
            "w_ace": "3", "w_df": "1", "w_svpt": "50", "w_1stIn": "30",
            "w_1stWon": "24", "w_2ndWon": "12", "w_bpSaved": "2", "w_bpFaced": "4",
        }, "winner"),
        ({
            "l_df": "2", "l_svpt": "40", "l_1stWon": "12", "l_2ndWon": "8",
            "l_bpSaved": "1", "l_bpFaced": "3",
        }, "loser"),
    ])

    assert stats["matches_with_service_stats"] == 2
    assert stats["matches_with_aces"] == 1
    assert stats["matches_with_double_faults"] == 2
    assert stats["matches_with_first_serve_stats"] == 1
    assert stats["matches_with_first_serve_points_won"] == 1
    assert stats["matches_with_second_serve_points_won"] == 1
    assert stats["matches_with_break_point_stats"] == 2
    assert stats["aces_per_match"] == 3.0
    assert stats["double_faults_per_match"] == 1.5
    assert stats["first_serve_in_pct"] == 0.6
    assert stats["first_serve_points_won_pct"] == 0.8
    assert stats["second_serve_points_won_pct"] == 0.6
    assert stats["break_points_saved_pct"] == 0.4286


def test_service_aggregator_excludes_inconsistent_match_level_counts():
    stats = _aggregate_service_stats([
        ({
            "w_ace": "55", "w_df": "1", "w_svpt": "50", "w_1stIn": "60",
            "w_1stWon": "61", "w_2ndWon": "30", "w_bpSaved": "5", "w_bpFaced": "4",
        }, "winner"),
    ])

    assert stats["matches_with_service_stats"] == 1
    assert stats["matches_with_aces"] == 0
    assert stats["matches_with_first_serve_stats"] == 0
    assert stats["matches_with_first_serve_points_won"] == 0
    assert stats["matches_with_second_serve_points_won"] == 0
    assert stats["matches_with_break_point_stats"] == 0
    assert stats["aces_per_match"] is None
    assert stats["first_serve_in_pct"] is None
    assert stats["break_points_saved_pct"] is None
