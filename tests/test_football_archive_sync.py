from pathlib import Path

from sync_football_archive import resolve_year_range


def test_archive_sync_defaults_to_current_and_previous_season():
    assert resolve_year_range(current_year=2026) == (2025, 2026)


def test_archive_sync_honors_manual_historical_range():
    assert resolve_year_range("2000", "2026", current_year=2026) == (2000, 2026)


def test_archive_sync_can_override_only_one_year_bound():
    assert resolve_year_range("2022", None, current_year=2026) == (2022, 2026)
    assert resolve_year_range(None, "2024", current_year=2026) == (2023, 2024)


def test_workflow_refreshes_archive_twice_daily():
    workflow = Path(".github/workflows/football_archive_sync.yml").read_text()
    assert 'cron: "17 5 * * *"' in workflow
    assert 'cron: "17 15 * * *"' in workflow
    assert "github.event.inputs.start_year || ''" in workflow
    assert "github.event.inputs.end_year || ''" in workflow


def test_archive_sync_distinguishes_missing_source_file_from_empty_csv(monkeypatch):
    import requests
    from types import SimpleNamespace

    import football_archive as archive

    monkeypatch.setattr(archive, "get_supabase_client", lambda: object())

    def missing_file(_competition, _season):
        raise requests.HTTPError(
            "404 Client Error",
            response=SimpleNamespace(status_code=404),
        )

    monkeypatch.setattr(archive, "_download_season", missing_file)
    result = archive.sync_football_archive(
        start_year=2026, end_year=2026, competitions=["PL"]
    )

    assert result["success"] is True
    assert result["available_files"] == 0
    assert result["unavailable_files"] == 1
    assert result["failed_files"] == 0
    assert result["season_results"] == [{
        "competition": "PL",
        "season": "2627",
        "status": "unavailable",
        "matches": 0,
    }]
    assert result["coverage_by_competition"][0]["unavailable_files"] == 1


def test_archive_sync_reports_available_season_with_zero_matches(monkeypatch):
    import football_archive as archive

    monkeypatch.setattr(archive, "get_supabase_client", lambda: object())
    monkeypatch.setattr(archive, "_download_season", lambda _competition, _season: [])

    result = archive.sync_football_archive(
        start_year=2026, end_year=2026, competitions=["PL"]
    )

    assert result["success"] is True
    assert result["available_files"] == 1
    assert result["unavailable_files"] == 0
    assert result["season_results"][0]["status"] == "available"
    assert result["season_results"][0]["matches"] == 0
    assert result["coverage_by_competition"][0]["seasons_with_zero_matches"] == 1
