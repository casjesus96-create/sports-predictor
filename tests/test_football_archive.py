from football_archive import (
    build_match_payload,
    normalize_team_key,
    parse_csv_matches,
    season_code,
)


def test_team_key_normalizes_accents_and_club_suffixes():
    assert normalize_team_key("Arsenal FC") == "arsenal"
    assert normalize_team_key("Málaga CF") == "malaga"
    assert normalize_team_key("Hull City AFC") == "hull"
    assert normalize_team_key("Hull City") == "hull"
    assert normalize_team_key("Manchester Utd") == "manchester united"
    assert normalize_team_key("Man City") == "manchester city"
    assert normalize_team_key("Spurs") == "tottenham"
    assert normalize_team_key("Leeds United FC") == "leeds"
    assert normalize_team_key("Tottenham Hotspur FC") == "tottenham"


def test_season_code_uses_two_digit_start_and_end_years():
    assert season_code(2025) == "2526"
    assert season_code(1999) == "9900"


def test_build_match_payload_requires_final_numeric_scores():
    valid = {
        "Date": "07/11/2026",
        "HomeTeam": "Arsenal",
        "AwayTeam": "Hull",
        "FTHG": "2",
        "FTAG": "0",
        "FTR": "H",
    }
    payload = build_match_payload(valid, "PL", "2627")
    assert payload is not None
    assert payload["home_score"] == 2
    assert payload["away_score"] == 0
    assert payload["result"] == "H"
    assert len(payload["source_key"]) == 64

    assert build_match_payload({**valid, "FTHG": ""}, "PL", "2627") is None
    assert build_match_payload({**valid, "FTAG": "N/A"}, "PL", "2627") is None
    assert build_match_payload({**valid, "HomeTeam": "Hull"}, "PL", "2627") is None


def test_csv_parser_skips_rows_without_final_result():
    content = (
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "E0,07/11/2026,Arsenal,Hull,2,0,H\n"
        "E0,08/11/2026,Leeds,Everton,,,\n"
    )
    rows = parse_csv_matches(content, "PL", "2627")
    assert len(rows) == 1
    assert rows[0]["home_team_key"] == "arsenal"



def test_h2h_queries_exact_pair_and_excludes_matches_after_kickoff(monkeypatch):
    import football_archive

    rows = [
        {
            "source_key": "leeds-tottenham-2025",
            "match_date": "2025-10-04",
            "season": "2526",
            "competition_name": "Premier League",
            "competition_code": "PL",
            "home_team": "Leeds",
            "home_team_key": "leeds",
            "away_team": "Tottenham",
            "away_team_key": "tottenham",
            "home_score": 1,
            "away_score": 2,
            "source": "football-data.co.uk",
        },
        {
            "source_key": "tottenham-leeds-2024",
            "match_date": "2024-05-11",
            "season": "2324",
            "competition_name": "Premier League",
            "competition_code": "PL",
            "home_team": "Tottenham",
            "home_team_key": "tottenham",
            "away_team": "Leeds",
            "away_team_key": "leeds",
            "home_score": 1,
            "away_score": 1,
            "source": "football-data.co.uk",
        },
        {
            "source_key": "leeds-tottenham-future",
            "match_date": "2026-11-08",
            "season": "2627",
            "competition_name": "Premier League",
            "competition_code": "PL",
            "home_team": "Leeds",
            "home_team_key": "leeds",
            "away_team": "Tottenham",
            "away_team_key": "tottenham",
            "home_score": 0,
            "away_score": 0,
            "source": "football-data.co.uk",
        },
    ]

    class FakeQuery:
        def __init__(self):
            self.filter = None

        def select(self, *_args, **_kwargs):
            return self

        def or_(self, expression):
            self.filter = expression
            captured["filter"] = expression
            return self

        def order(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def execute(self):
            return type("Result", (), {"data": rows})()

    captured = {}
    query = FakeQuery()

    class FakeClient:
        def table(self, table_name):
            assert table_name == "football_match_archive"
            return query

    monkeypatch.setattr(football_archive, "get_supabase_client", lambda: FakeClient())

    result = football_archive.archive_head_to_head(
        competition="PL",
        home_team="Leeds United FC",
        away_team="Tottenham Hotspur FC",
        kickoff_at="2026-11-07T08:30:00Z",
        limit=20,
    )

    assert result["availability"] == "available"
    assert result["sample_size"] == 2
    assert result["returned_matches"] == 2
    assert result["provider_calls"] == 0
    assert result["teams"]["home"]["key"] == "leeds"
    assert result["teams"]["away"]["key"] == "tottenham"
    assert "and(home_team_key.eq.leeds,away_team_key.eq.tottenham)" in captured["filter"]
    assert "and(home_team_key.eq.tottenham,away_team_key.eq.leeds)" in captured["filter"]
    assert [match["date"] for match in result["meetings"]] == ["2025-10-04", "2024-05-11"]
    assert result["summary"]["away_team_wins"] == 1
    assert result["summary"]["draws"] == 1


def test_safe_team_search_removes_postgrest_filter_syntax():
    from football_archive import _safe_team_search

    assert _safe_team_search("Hull City AFC") == "Hull City AFC"
    assert _safe_team_search("A,B%_C") == "A B C"


def test_resolver_prefers_confirmed_competition_alias():
    import football_archive

    class Query:
        def __init__(self, rows):
            self.rows = rows
        def select(self, *_args, **_kwargs): return self
        def eq(self, *_args, **_kwargs): return self
        def limit(self, *_args, **_kwargs): return self
        def execute(self): return type("Result", (), {"data": self.rows})()

    class Client:
        def table(self, name):
            if name == "football_team_aliases":
                return Query([{"canonical_team_key": "hull"}])
            raise AssertionError(f"Unexpected table access: {name}")

    key, resolution = football_archive._resolve_team_identity(Client(), "PL", "The Tigers")
    assert key == "hull"
    assert resolution == "verified_alias"


def test_resolver_uses_exact_archive_key_when_no_alias_exists():
    import football_archive

    class Query:
        def __init__(self, rows): self.rows = rows
        def select(self, *_args, **_kwargs): return self
        def eq(self, *_args, **_kwargs): return self
        def limit(self, *_args, **_kwargs): return self
        def execute(self): return type("Result", (), {"data": self.rows})()

    class Client:
        def table(self, name):
            if name == "football_team_aliases": return Query([])
            if name == "football_archive_teams": return Query([{"canonical_team_key": "arsenal"}])
            raise AssertionError(f"Unexpected table access: {name}")

    key, resolution = football_archive._resolve_team_identity(Client(), "PL", "Arsenal FC")
    assert key == "arsenal"
    assert resolution == "exact"
