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
])
def test_invalid_rows_are_rejected_without_guessing(overrides):
    assert archive.build_match_payload(row(**overrides), "2026-11-18T00:00:00+00:00") is None



def test_missing_publisher_match_id_uses_deterministic_namespaced_identity():
    imported_at = "2026-11-18T00:00:00+00:00"
    first = archive.build_match_payload(row(match_id=""), imported_at)
    second = archive.build_match_payload(row(match_id=""), imported_at)
    reversed_players = archive.build_match_payload(
        row(match_id="", joueur1="Player Two", joueur1_id="202",
            joueur2="Player One", joueur2_id="101"), imported_at
    )

    assert first is not None
    assert first["source_match_id"].startswith("derived:")
    assert first["source_match_id"] == second["source_match_id"]
    assert first["source_match_id"] == reversed_players["source_match_id"]


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



@pytest.mark.parametrize(
    ("surface_detail", "expected_surface"),
    [
        ("Hard", "Hard"),
        ("Indoor Hard", "Hard"),
        ("I.hard", "Hard"),
        ("dur", "Hard"),
        ("dur intérieur", "Hard"),
        ("dur intÃ©rieur", "Hard"),
        ("Clay", "Clay"),
        ("terre battue", "Clay"),
        ("Grass", "Grass"),
        ("gazon", "Grass"),
        ("Carpet", "Carpet"),
        ("moquette intérieur", "Carpet"),
        ("moquette intÃ©rieur", "Carpet"),
        ("unknown court", "Other"),
        ("", None),
    ],
)
def test_surface_normalization_supports_english_french_and_mojibake(
    surface_detail, expected_surface
):
    payload = archive.build_match_payload(
        row(surface=surface_detail),
        "2026-11-18T00:00:00+00:00",
    )
    assert payload["surface"] == expected_surface
    assert payload["surface_detail"] == (surface_detail or None)

def test_indoor_hard_is_grouped_as_hard_but_raw_label_is_preserved():
    payload = archive.build_match_payload(
        row(surface="I.hard"),
        "2026-11-18T00:00:00+00:00",
    )
    assert payload["surface"] == "Hard"
    assert payload["surface_detail"] == "I.hard"



class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, _columns):
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def gte(self, key, value):
        self.filters.append(("gte", key, value))
        return self

    def lt(self, key, value):
        self.filters.append(("lt", key, value))
        return self

    def order(self, _key, desc=False):
        return self

    def limit(self, _count):
        return self

    def execute(self):
        data = list(self.rows)
        for operator, key, value in self.filters:
            if operator == "eq":
                data = [row for row in data if row.get(key) == value]
            elif operator == "gte":
                data = [row for row in data if str(row.get(key) or "") >= value]
            elif operator == "lt":
                data = [row for row in data if str(row.get(key) or "") < value]
        if any(key == "match_date" for _, key, _ in self.filters) and len(data) > 0:
            data.sort(key=lambda row: str(row.get("match_date") or ""))
        if len(data) == 0 and self.filters == []:
            return FakeResponse([])
        if any(key == "league" for _, key, _ in self.filters) and any(key == "player1_name_key" for _, key, _ in self.filters):
            return FakeResponse(data)
        if any(key == "league" for _, key, _ in self.filters) and any(key == "player2_name_key" for _, key, _ in self.filters):
            return FakeResponse(data)
        if any(key == "league" for _, key, _ in self.filters):
            return FakeResponse(data[-1:] if data else [])
        return FakeResponse(data)


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def select(self, columns):
        return FakeQuery(self.rows).select(columns)


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return FakeTable(self.rows)


def archive_row(match_id, match_date, p1_id, p1_name, p2_id, p2_name, winner_id, surface="Hard", category="Main tour"):
    return {
        "source_match_id": match_id,
        "league": "ATP",
        "match_date": match_date,
        "match_datetime_utc": f"{match_date}T12:00:00+00:00",
        "tournament": "Test Open",
        "category": category,
        "surface": surface,
        "round_code": 12,
        "player1_id": p1_id,
        "player1_name": p1_name,
        "player1_name_key": archive.normalize_player_name(p1_name),
        "player2_id": p2_id,
        "player2_name": p2_name,
        "player2_name_key": archive.normalize_player_name(p2_name),
        "winner_id": winner_id,
        "score": "6-4 6-3",
    }


def test_persisted_profile_uses_exact_match_dates_and_stable_player_id(monkeypatch):
    from datetime import date

    rows = [
        archive_row("m1", "2026-11-10", "303", "Player Three", "101", "Player One", "303", "Clay"),
        archive_row("m2", "2026-11-17", "101", "Player One", "202", "Player Two", "101", "Hard"),
    ]
    monkeypatch.setattr(archive, "get_supabase_client", lambda: FakeClient(rows))

    profile = archive.get_player_archive_profile(
        "Player One", "ATP", date(2026, 11, 18), 365
    )

    assert profile["matches_in_window"] == 2
    assert profile["wins_in_window"] == 1
    assert profile["losses_in_window"] == 1
    assert profile["days_since_last_match"] == 1
    assert profile["recent_matches"][0]["date"] == "2026-11-17"
    assert profile["recent_matches"][0]["date_precision"] == "exact_match_date"
    assert profile["recent_matches"][0]["opponent"] == "Player Two"
    assert profile["surface_window"]["matches"] == 2
    assert profile["service_return_stats_last_10_matches"]["aces_per_match"] is None
    assert profile["data_quality"]["source_data_age_days"] == 1


def test_persisted_profile_exposes_challenger_category_without_merging_player_identity(monkeypatch):
    from datetime import date

    rows = [
        archive_row("main-1", "2026-11-10", "101", "Player One", "202", "Player Two", "101"),
        archive_row(
            "challenger-1", "2026-11-17", "101", "Player One", "303", "Player Three", "303",
            category="Challenger",
        ),
    ]
    monkeypatch.setattr(archive, "get_supabase_client", lambda: FakeClient(rows))

    profile = archive.get_player_archive_profile(
        "Player One", "ATP", date(2026, 11, 18), 365
    )

    assert profile["matches_in_window"] == 2
    assert {item["category"] for item in profile["recent_matches"]} == {"Main tour", "Challenger"}
    assert "no alimenta las proyecciones ni los backtests Elo" in profile["data_quality"]["warning"]


def test_persisted_profile_refuses_ambiguous_name_to_player_id(monkeypatch):
    from datetime import date

    rows = [
        archive_row("m1", "2026-11-10", "101", "Player One", "202", "Player Two", "101"),
        archive_row("m2", "2026-11-17", "999", "Player One", "303", "Player Three", "999"),
    ]
    monkeypatch.setattr(archive, "get_supabase_client", lambda: FakeClient(rows))

    profile = archive.get_player_archive_profile(
        "Player One", "ATP", date(2026, 11, 18), 365
    )

    assert profile == {"identity_ambiguous": True}


def test_same_source_match_id_can_exist_in_both_tours():
    atp = row(genre="ATP")
    wta = row(genre="WTA", joueur1_id="501", joueur2_id="502", vainqueur_id="501")
    parsed = archive.parse_year_rows(
        (atp, wta), 2026, "2026-11-18T00:00:00+00:00"
    )
    assert len(parsed["rows"]) == 2
    assert {item["league"] for item in parsed["rows"]} == {"ATP", "WTA"}
    assert parsed["league_counts"]["ATP"]["source_rows"] == 1
    assert parsed["league_counts"]["ATP"]["eligible_matches"] == 1
    assert parsed["league_counts"]["WTA"]["source_rows"] == 1
    assert parsed["league_counts"]["WTA"]["eligible_matches"] == 1


@pytest.mark.parametrize("league", ["ATP", "WTA"])
def test_import_includes_challenger_for_both_tours_but_excludes_itf(league):
    challenger = row(
        genre=league,
        categorie="Challenger",
        joueur1_id="501",
        joueur2_id="502",
        vainqueur_id="501",
        match_id=f"{league.lower()}-challenger-2026",
    )
    parsed = archive.parse_year_rows(
        (challenger, row(genre=league, categorie="ITF", match_id=f"{league.lower()}-itf-2026")),
        2026,
        "2026-11-18T00:00:00+00:00",
    )
    assert len(parsed["rows"]) == 1
    assert parsed["rows"][0]["league"] == league
    assert parsed["rows"][0]["category"] == "Challenger"
    assert parsed["league_counts"][league]["category_counts"]["challenger"] == 1
    assert parsed["league_counts"][league]["category_counts"]["itf"] == 1
    assert parsed["rows_excluded_category"] == 1
    assert parsed["rows_rejected"] == 0


def test_archive_player_name_key_matches_profile_normalization_rules():
    assert archive.normalize_player_name("João  &  Co.") == "joao and co"



def test_parse_year_rows_reports_category_and_validation_diagnostics():
    parsed = archive.parse_year_rows(
        (
            row(categorie="Main tour", joueur1_id="", joueur2_id="202"),
            row(categorie="Challenger", match_id="valid-challenger"),
            row(categorie="Grand Chelem", match_id="valid-grand-chelem"),
        ),
        2026,
        "2026-11-18T00:00:00+00:00",
    )
    assert parsed["category_counts"] == {
        "challenger": 1,
        "grand chelem": 1,
        "main tour": 1,
    }
    assert parsed["rejection_reasons"] == {"missing_player_id": 1}
    assert len(parsed["rows"]) == 2
    assert {item["category"] for item in parsed["rows"]} == {"Challenger", "Grand Chelem"}


def test_csv_reader_normalizes_bom_and_header_whitespace():
    from tennis_external_source import _read_csv

    csv_text = (
        "\ufeffmatch_id ; date ; tournoi ; categorie ; genre ; surface ; tour ; "
        "joueur1 ; joueur1_id ; joueur2 ; joueur2_id ; vainqueur_id\n"
        "m-1;2026-11-17T12:00:00+00:00;Test Open;Main tour;ATP;Hard;12;"
        "Player One;101;Player Two;202;101\n"
    )
    parsed = _read_csv(csv_text)
    assert len(parsed) == 1
    assert parsed[0]["match_id"] == "m-1"
    assert parsed[0]["categorie"] == "Main tour"
    assert parsed[0]["genre"] == "ATP"



def test_sync_does_not_report_success_when_no_eligible_matches(monkeypatch):
    class EmptyWriteQuery:
        def upsert(self, *_args, **_kwargs):
            raise AssertionError("No rows should be written")

    class EmptyWriteClient:
        def table(self, _name):
            return EmptyWriteQuery()

    monkeypatch.setattr(archive, "get_supabase_client", lambda: EmptyWriteClient())
    monkeypatch.setattr(archive, "load_external_year", lambda _year: (row(categorie="ITF"),))

    result = archive.sync_tennis_archive(start_year=2026, end_year=2026)

    assert result["success"] is False
    assert result["status"] == "no_eligible_matches"
    assert result["valid_matches"] == 0
    assert result["by_year"][0]["status"] == "no_eligible_matches"

def test_sync_reports_missing_wta_instead_of_success_when_only_atp_is_present(monkeypatch):
    writes = []

    class WriteQuery:
        def upsert(self, payload, **_kwargs):
            writes.extend(payload)
            return self

        def execute(self):
            return None

    class WriteClient:
        def table(self, _name):
            return WriteQuery()

    monkeypatch.setattr(archive, "get_supabase_client", lambda: WriteClient())
    monkeypatch.setattr(archive, "load_external_year", lambda _year: (row(genre="ATP"),))

    result = archive.sync_tennis_archive(start_year=2026, end_year=2026)

    assert result["success"] is False
    assert result["status"] == "missing_league_data"
    assert result["missing_leagues"] == ["WTA"]
    assert result["by_league"]["ATP"]["upserted_rows"] == 1
    assert result["by_league"]["WTA"]["source_rows"] == 0
    assert result["by_year"][0]["leagues"]["ATP"]["upserted_rows"] == 1
    assert result["by_year"][0]["leagues"]["WTA"]["eligible_matches"] == 0
    assert len(writes) == 1
