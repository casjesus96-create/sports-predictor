import pytest

import nhl_archive as archive


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


def test_deduplicates_cross_team_observations_and_marks_confirmed_regular_game_eligible():
    source = game()
    parsed = archive.build_archive_payloads(
        "20252026",
        {"TOR": {"games": [source]}, "BOS": {"games": [source]}},
        "2026-11-20T00:00:00+00:00",
    )
    assert parsed["unique_games"] == 1
    assert parsed["training_eligible_games"] == 1
    row = parsed["rows"][0]
    assert row["game_id"] == "2025020001"
    assert row["cross_team_confirmed"] is True
    assert row["observed_teams"] == ["BOS", "TOR"]
    assert row["source_terms_status"] == "review_required"


def test_keeps_external_exhibition_opponent_but_excludes_it_from_training():
    exhibition = game(
        game_id="2024010106", home="MUN", away="BUF", game_type=1, game_date="2024-09-27"
    )
    parsed = archive.build_archive_payloads(
        "20242025", {"BUF": {"games": [exhibition]}},
        "2026-11-20T00:00:00+00:00",
    )
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
    parsed = archive.build_archive_payloads(
        "20242025",
        {"TBL": {"games": [pending]}, "NSH": {"games": [pending]}},
        "2026-11-20T00:00:00+00:00",
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
        archive.build_archive_payloads(
            "20252026",
            {"TOR": {"games": [first]}, "BOS": {"games": [second]}},
            "now",
        )


def test_rejects_completed_game_without_both_scores():
    invalid = game()
    invalid["away"]["score"] = None
    with pytest.raises(archive.NHLArchiveImportError, match="marcadores válidos"):
        archive.build_archive_payloads(
            "20252026", {"TOR": {"games": [invalid]}}, "now"
        )


def test_preseason_nhl_match_is_retained_but_not_training_eligible():
    preseason = game(game_id="2025010001", game_type=1)
    parsed = archive.build_archive_payloads(
        "20252026",
        {"TOR": {"games": [preseason]}, "BOS": {"games": [preseason]}},
        "now",
    )
    assert parsed["unique_games"] == 1
    assert parsed["training_eligible_games"] == 0
    assert parsed["rows"][0]["result_status"] == "FINAL"


def test_rejects_missing_game_type_and_invalid_team_identity():
    invalid = game()
    invalid["game_type"] = None
    with pytest.raises(archive.NHLArchiveImportError, match="game_type"):
        archive.build_archive_payloads("20252026", {"TOR": {"games": [invalid]}}, "now")


def test_sync_uses_idempotent_game_id_upsert(monkeypatch):
    writes = []

    class Query:
        def upsert(self, payload, on_conflict):
            writes.extend(payload)
            assert on_conflict == "game_id"
            return self

        def execute(self):
            return None

    class Client:
        def table(self, name):
            assert name == "nhl_game_archive"
            return Query()

    monkeypatch.setattr(archive, "get_team_season_schedule", lambda team, season: {
        "games": [game()] if team in {"TOR", "BOS"} else []
    })
    monkeypatch.setattr(archive, "CURRENT_TEAM_ABBREVIATIONS", ("TOR", "BOS"))
    monkeypatch.setattr(archive, "get_supabase_client", Client)
    result = archive.import_nhl_season("20252026")
    assert result["success"] is True
    assert result["upserted_rows"] == 1
    assert len(writes) == 1


def test_import_aborts_before_database_writes_when_a_team_schedule_fails(monkeypatch):
    writes = []

    class Client:
        def table(self, _name):
            raise AssertionError("No DB writes should occur")

    def schedule(team, _season):
        if team == "BOS":
            raise archive.NHLDataError("upstream unavailable")
        return {"games": [game()]} if team == "TOR" else {"games": []}

    monkeypatch.setattr(archive, "get_team_season_schedule", schedule)
    monkeypatch.setattr(archive, "CURRENT_TEAM_ABBREVIATIONS", ("TOR", "BOS"))
    with pytest.raises(archive.NHLArchiveImportError, match="Auditoría estructural fallida"):
        archive.import_nhl_season("20252026", client=Client())
    assert writes == []
