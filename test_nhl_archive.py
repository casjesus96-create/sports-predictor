import pytest

import nhl_archive as archive


SOURCE = {
    "source_name": "Test licensed dataset",
    "source_url": "https://example.org/nhl-data.csv",
    "source_license": "CC0",
    "source_attribution": "Test fixture released under CC0",
    "source_terms_status": "reviewed",
}


def game(game_id="2025020001", home="TOR", away="BOS", game_type=2, completed=True, game_date="2025-10-08"):
    return {
        "game_id": game_id,
        "game_date": game_date,
        "start_time_utc": "2025-10-08T23:00:00Z",
        "game_state": "OFF" if completed else "FUT",
        "completed": completed,
        "game_type": game_type,
        "home": {"id": 10, "abbreviation": home, "name": home, "score": 3 if completed else None},
        "away": {"id": 20, "abbreviation": away, "name": away, "score": 2 if completed else None},
    }


def build(season, schedules, **source_overrides):
    provenance = {**SOURCE, **source_overrides}
    return archive.build_archive_payloads(
        season, schedules, "2026-11-20T00:00:00+00:00", **provenance
    )


def test_deduplicates_cross_team_observations_and_marks_confirmed_regular_game_eligible():
    source = game()
    parsed = build(
        "20252026",
        {"TOR": {"games": [source]}, "BOS": {"games": [source]}},
    )
    assert parsed["unique_games"] == 1
    assert parsed["training_eligible_games"] == 1
    row = parsed["rows"][0]
    assert row["game_id"] == "2025020001"
    assert row["cross_team_confirmed"] is True
    assert row["observed_teams"] == ["BOS", "TOR"]
    assert row["source_terms_status"] == "reviewed"
    assert row["source_license"] == "CC0"


def test_keeps_external_exhibition_opponent_but_excludes_it_from_training():
    exhibition = game(
        game_id="2024010106", home="MUN", away="BUF",
        game_type=1, game_date="2024-09-27",
    )
    parsed = build("20242025", {"BUF": {"games": [exhibition]}})
    row = parsed["rows"][0]
    assert row["home_team_abbreviation"] == "MUN"
    assert row["away_team_abbreviation"] == "BUF"
    assert row["cross_team_confirmed"] is False
    assert row["training_eligible"] is False
    assert row["eligibility_reason"] == "preseason_or_exhibition_not_eligible"


def test_preserves_nonfinal_game_without_claiming_it_was_cancelled():
    pending = game(
        game_id="2024010044", home="TBL", away="NSH",
        game_type=1, completed=False, game_date="2024-10-07",
    )
    parsed = build(
        "20242025",
        {"TBL": {"games": [pending]}, "NSH": {"games": [pending]}},
    )
    row = parsed["rows"][0]
    assert row["result_status"] == "NON_FINAL_REVIEW"
    assert row["training_eligible"] is False
    assert "cancel" not in row["eligibility_reason"]


def test_rejects_conflicting_duplicate_observations():
    first = game()
    second = game()
    second["home"]["score"] = 4
    with pytest.raises(archive.NHLArchiveImportError, match="contradictorios"):
        build("20252026", {"TOR": {"games": [first]}, "BOS": {"games": [second]}})


def test_rejects_completed_game_without_both_scores():
    invalid = game()
    invalid["away"]["score"] = None
    with pytest.raises(archive.NHLArchiveImportError, match="marcadores válidos"):
        build("20252026", {"TOR": {"games": [invalid]}})


def test_preseason_nhl_match_is_retained_but_not_training_eligible():
    preseason = game(game_id="2025010001", game_type=1)
    parsed = build(
        "20252026",
        {"TOR": {"games": [preseason]}, "BOS": {"games": [preseason]}},
    )
    assert parsed["unique_games"] == 1
    assert parsed["training_eligible_games"] == 0
    assert parsed["rows"][0]["result_status"] == "FINAL"


def test_rejects_missing_game_type_and_invalid_team_identity():
    invalid = game()
    invalid["game_type"] = None
    with pytest.raises(archive.NHLArchiveImportError, match="game_type"):
        build("20252026", {"TOR": {"games": [invalid]}})


def test_rejects_truthy_string_completed_flag():
    invalid = game(completed="false")
    with pytest.raises(archive.NHLArchiveImportError, match="completed.*booleano"):
        build("20252026", {"TOR": {"games": [invalid]}})


@pytest.mark.parametrize("invalid_type", [True, False, "1", 1.0, 0, 4, None])
def test_rejects_non_integer_or_out_of_range_game_type(invalid_type):
    invalid = game(game_type=invalid_type)
    with pytest.raises(archive.NHLArchiveImportError, match="game_type"):
        build("20252026", {"TOR": {"games": [invalid]}})


def test_normalizes_requested_team_abbreviation_case():
    source = game(home="TOR", away="BOS")
    parsed = build("20252026", {" tor ": {"games": [source]}})
    assert parsed["rows"][0]["home_team_abbreviation"] == "TOR"


def test_rejects_malformed_schedule_container():
    with pytest.raises(archive.NHLArchiveImportError, match="formato inválido"):
        build("20252026", {"TOR": {"games": "not-a-list"}})


def test_rejects_unreviewed_or_incomplete_source_provenance():
    source = game()
    with pytest.raises(ValueError, match="revisión de términos"):
        build(
            "20252026",
            {"TOR": {"games": [source]}},
            source_terms_status="review_required",
        )
    with pytest.raises(ValueError, match="son obligatorias"):
        build("20252026", {"TOR": {"games": [source]}}, source_license="")
