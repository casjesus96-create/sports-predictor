from pathlib import Path

from sync_football_archive import resolve_year_range


def test_archive_sync_defaults_to_current_and_previous_season():
    assert resolve_year_range(current_year=2026) == (2025, 2026)


def test_archive_sync_honors_manual_historical_range():
    assert resolve_year_range("2000", "2026", current_year=2026) == (2000, 2026)


def test_archive_sync_can_override_only_one_year_bound():
    assert resolve_year_range("2022", None, current_year=2026) == (2022, 2026)
    assert resolve_year_range(None, "2024", current_year=2026) == (2025, 2024)


def test_workflow_refreshes_archive_twice_daily():
    workflow = Path(".github/workflows/football_archive_sync.yml").read_text()
    assert 'cron: "17 5 * * *"' in workflow
    assert 'cron: "17 15 * * *"' in workflow
    assert "github.event.inputs.start_year || ''" in workflow
    assert "github.event.inputs.end_year || ''" in workflow
