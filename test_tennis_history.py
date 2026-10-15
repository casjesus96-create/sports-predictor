from datetime import date

import pytest

from tennis_history import (
    _aggregate_service_stats,
    get_player_profile,
    normalize_player_name,
    parse_cutoff,
)


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
    assert profile["ranking_latest_in_window"] == 11
    assert profile["data_quality"]["matches_with_service_stats"] == 2


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
