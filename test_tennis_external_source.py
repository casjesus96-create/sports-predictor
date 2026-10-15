from datetime import date

import pytest

import tennis_external_source as source


def source_row(day, league="ATP", category="Main tour", winner="1"):
    return {
        "date": f"{day}T14:30:00+00:00",
        "genre": league,
        "categorie": category,
        "joueur1": "Player One",
        "joueur2": "Player Two",
        "joueur1_id": "1",
        "joueur2_id": "2",
        "vainqueur_id": winner,
        "match_id": f"{day}-{league}",
    }


def test_external_audit_reports_monthly_coverage_without_merging(monkeypatch):
    rows = (
        source_row("2026-06-10"),
        source_row("2026-08-20", category="Challenger"),
        source_row("2026-09-01", league="WTA"),
        source_row("2026-09-02", winner="invalid"),
    )
    monkeypatch.setattr(source, "load_external_year", lambda year: rows if year == 2026 else ())
    result = source.audit_external_coverage("ATP", "2026-06-01", "2026-09-30")

    assert result["status"] == "source_audit_only"
    assert result["model_status"] == "research_only"
    assert result["coverage"]["valid_matches_in_window"] == 2
    assert result["coverage"]["coverage_start_date"] == "2026-06-10"
    assert result["coverage"]["coverage_end_date"] == "2026-08-20"
    assert result["coverage"]["months_without_matches"] == ["2026-07", "2026-09"]
    assert result["coverage"]["monthly_breakdown"][2]["categories"] == {"Challenger": 1}
    assert "not merged" in " ".join(result["limitations"]).lower()
    assert result["source"]["license"] == "CC BY 4.0"


def test_external_audit_rejects_invalid_league_and_long_window():
    with pytest.raises(ValueError, match="ATP o WTA"):
        source.audit_external_coverage("ITF", "2026-06-01", "2026-06-30")
    with pytest.raises(ValueError, match="366 días"):
        source.audit_external_coverage("ATP", "2026-01-01", "2027-01-02")


def test_external_csv_parser_rejects_unexpected_schema():
    with pytest.raises(source.ExternalTennisSourceError, match="esquema"):
        source._read_csv("date,genre,winner\\n2026-06-01,ATP,Player One\\n")


def test_match_day_converts_timestamp_to_utc_date():
    assert source._match_day("2026-06-01T00:30:00+02:00") == date(2026, 5, 31)
    assert source._match_day("not-a-date") is None
