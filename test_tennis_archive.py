from datetime import datetime, timezone

import pytest

import tennis_archive as archive


def row(**overrides):
    values = {
        "match_id": "vb-2026-001",
        "date": "2026-11-17T14:30:00+00:00",
        "tournoi": "ATP Finals",
        "tournoi_id": "atp-finals-2026",
        "categorie": "Masters",
        "genre": "ATP",
        "surface": "Hard",
        "tour": "12",
        "joueur1": "Player One",
        "joueur1_id": "101",
        "joueur2": "Player Two",
        "joueur2_id": "202",
        "vainqueur_id": "101",
        "score": "6-4 7-5",
        "duree_min": "98",
    }
    values.update(overrides)
    return values


def test_build_match_payload_preserves_exact_date_surface_and_provenance():
    imported_at = datetime(2026, 11, 18, tzinfo=timezone.utc).isoformat()
    payload = archive.build_match_payload(row(), imported_at)

    assert payload["source_match_id"] == "vb-2026-001"
    assert payload["league"] == "ATP"
    assert payload["match_date"] == "2026-11-17"
    assert payload["match_datetime_utc"] == "2026-11-17T14:30:00+00:00"
    assert payload["surface"] == "Hard"
    assert payload["surface_detail"] == "Hard"
    assert payload["winner_id"] == "101"
    assert payload["source_license"] == "CC BY 4.0"
    assert "Valuebetennis" in payload["source_attribution"]


@pytest.mark.parametrize("overrides", [
    {"genre": "ITF"},
    {"vainqueur_id": "999"},
    {"joueur1_id": "202"},
    {"joueur1": " "},
    {"date": "not-a-date"},
    {"match_id": ""},
])
def test_invalid_rows_are_rejected_without_guessing(overrides):
    assert archive.build_match_payload(row(**overrides), "2026-11-18T00:00:00+00:00") is None


def test_parse_year_rows_deduplicates_identical_ids_and_rejects_conflicts():
    imported_at = "2026-11-18T00:00:00+00:00"
    parsed = archive.parse_year_rows((row(), row()), 2026, imported_at)
    assert len(parsed["rows"]) == 1
    assert parsed["duplicate_rows"] == 1
    assert parsed["rows_rejected"] == 0

    with pytest.raises(archive.TennisArchiveImportError, match="contradictorios"):
        archive.parse_year_rows(
            (row(), row(score="6-0 6-0", vainqueur_id="202")),
            2026,
            imported_at,
        )


def test_parse_year_rows_rejects_rows_outside_requested_year():
    parsed = archive.parse_year_rows((row(date="2025-12-31T23:00:00+00:00"),), 2026, "now")
    assert parsed["rows"] == []
    assert parsed["rows_rejected"] == 1


def test_resolve_year_range_defaults_and_manual_full_backfill():
    from sync_tennis_archive import resolve_year_range

    assert resolve_year_range(current_year=2026) == (2025, 2026)
    assert resolve_year_range("2021", "2026", 2026) == (2021, 2026)


def test_indoor_hard_is_grouped_as_hard_but_raw_label_is_preserved():
    payload = archive.build_match_payload(
        row(surface="I.hard"),
        "2026-11-18T00:00:00+00:00",
    )
    assert payload["surface"] == "Hard"
    assert payload["surface_detail"] == "I.hard"
