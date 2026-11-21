import pytest

from nhl_identity_registry_audit import (
    build_identity_registry_audit,
    render_markdown_summary,
)


def test_audit_reports_season_scoped_registry_without_claiming_completeness():
    report = build_identity_registry_audit(2023, 2025)
    assert report["success"] is True
    assert report["scope"] == "local_registry_only_no_network_no_database_writes"
    assert report["historical_seasons_included"] == 3
    by_season = {row["season"]: row for row in report["seasons"]}
    assert "ARI" in by_season["2023-2024"]["registered_abbreviations"]
    assert "UTA" not in by_season["2023-2024"]["registered_abbreviations"]
    assert "UTA" in by_season["2024-2025"]["registered_abbreviations"]
    assert any("no demuestra" in item for item in report["limitations"])


def test_audit_flags_unknown_observed_abbreviations_without_mapping_them():
    report = build_identity_registry_audit(
        2024,
        2024,
        {"2024-2025": ["UTA", "XYZ", "xyz"]},
    )
    assert report["success"] is False
    assert report["unknown_observed_abbreviations"] == [
        {"season": "2024-2025", "abbreviation": "XYZ"}
    ]
    assert "XYZ" not in report["seasons"][0]["registered_abbreviations"]


def test_audit_groups_historical_abbreviations_by_statistical_key():
    report = build_identity_registry_audit(1996, 1996)
    season = report["seasons"][0]
    assert "PHX" in season["statistical_groups"]["ARI"]
    assert "HFD" in season["statistical_groups"]["CAR"]


def test_markdown_summary_includes_scope_and_limitations():
    report = build_identity_registry_audit(2024, 2024)
    summary = render_markdown_summary(report)
    assert "identity registry audit" in summary
    assert "local_registry_only_no_network_no_database_writes" in summary
    assert "no demuestra" in summary


@pytest.mark.parametrize(
    ("start", "end"),
    [(2025, 2024), (1916, 1917), (1917, 9999)],
)
def test_audit_rejects_invalid_year_ranges(start, end):
    with pytest.raises((TypeError, ValueError)):
        build_identity_registry_audit(start, end)


def test_audit_rejects_boolean_year_values():
    with pytest.raises(TypeError):
        build_identity_registry_audit(True, 2024)
