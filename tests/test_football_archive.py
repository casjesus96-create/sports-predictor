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

        def eq(self, column, value):
            captured.setdefault("eq_filters", []).append((column, value))
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
    assert result["scope"] == "all"
    assert result["summary"]["home_team_clean_sheets"] == 0
    assert result["summary"]["away_team_clean_sheets"] == 0
    assert result["summary"]["away_team_clean_sheets_percentage"] == 0.0

    filtered = football_archive.archive_head_to_head(
        competition="PL",
        home_team="Leeds United FC",
        away_team="Tottenham Hotspur FC",
        scope="competition",
    )
    assert filtered["scope"] == "competition"
    assert ("competition_code", "PL") in captured["eq_filters"]


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



def test_h2h_summary_calculates_goal_markets_and_venue_splits():
    from football_archive import _summarize_head_to_head

    meetings = [
        {"_selected_home_result":"home","_selected_home_goals":2,"_selected_away_goals":1,"_selected_home_venue":"home","_selected_away_venue":"away","home_score":2,"away_score":1,"total_goals":3},
        {"_selected_home_result":"away","_selected_home_goals":0,"_selected_away_goals":2,"_selected_home_venue":"away","_selected_away_venue":"home","home_score":2,"away_score":0,"total_goals":2},
        {"_selected_home_result":"draw","_selected_home_goals":1,"_selected_away_goals":1,"_selected_home_venue":"home","_selected_away_venue":"away","home_score":1,"away_score":1,"total_goals":2},
        {"_selected_home_result":"home","_selected_home_goals":3,"_selected_away_goals":2,"_selected_home_venue":"away","_selected_away_venue":"home","home_score":2,"away_score":3,"total_goals":5},
    ]
    result = _summarize_head_to_head(meetings)
    assert (result["home_team_wins"], result["draws"], result["away_team_wins"]) == (2,1,1)
    assert result["both_teams_scored_count"] == 3
    assert result["both_teams_scored_percentage"] == 75.0
    assert result["home_team_clean_sheets"] == 0
    assert result["away_team_clean_sheets"] == 1
    assert result["away_team_clean_sheets_percentage"] == 25.0
    assert result["home_team_failed_to_score_count"] == 1
    assert result["away_team_failed_to_score_count"] == 0
    assert (result["over_1_5_count"], result["over_2_5_count"], result["over_3_5_count"]) == (4,2,1)
    assert (result["under_1_5_count"], result["under_2_5_count"], result["under_3_5_count"]) == (0,2,3)
    assert result["venue_split"]["home_team"]["at_home"]["matches"] == 2
    assert result["venue_split"]["home_team"]["at_home"]["wins"] == 1
    assert result["venue_split"]["home_team"]["away"]["matches"] == 2
    assert result["venue_split"]["away_team"]["at_home"]["matches"] == 2


def test_h2h_summary_handles_empty_history_without_fake_percentages():
    from football_archive import _summarize_head_to_head
    result = _summarize_head_to_head([])
    assert result["average_total_goals"] is None
    assert result["over_2_5_count"] == 0
    assert result["over_2_5_percentage"] is None
    assert result["both_teams_scored_percentage"] is None
    assert result["home_team_clean_sheets_percentage"] is None
    assert result["home_team_failed_to_score_percentage"] is None
    assert result["venue_split"]["home_team"]["at_home"]["matches"] == 0



def test_team_form_summary_uses_latest_windows_and_does_not_pad_samples():
    from football_archive import _summarize_team_form

    matches = [
        {"result":"W","points":3,"goals_for":2,"goals_against":0,"total_goals":2,"venue":"home"},
        {"result":"D","points":1,"goals_for":1,"goals_against":1,"total_goals":2,"venue":"away"},
        {"result":"L","points":0,"goals_for":0,"goals_against":2,"total_goals":2,"venue":"home"},
        {"result":"W","points":3,"goals_for":3,"goals_against":1,"total_goals":4,"venue":"away"},
        {"result":"W","points":3,"goals_for":1,"goals_against":0,"total_goals":1,"venue":"home"},
        {"result":"D","points":1,"goals_for":2,"goals_against":2,"total_goals":4,"venue":"away"},
    ]
    result = _summarize_team_form(matches)

    assert result["5"]["matches"] == 5
    assert result["5"]["sample_complete"] is True
    assert result["5"]["wins"] == 3
    assert result["5"]["draws"] == 1
    assert result["5"]["losses"] == 1
    assert result["5"]["points"] == 10
    assert result["5"]["form_sequence"] == ["W", "W", "L", "D", "W"]
    assert result["5"]["clean_sheets"] == 2
    assert result["5"]["failed_to_score"] == 1
    assert result["5"]["venue_split"]["at_home"]["matches"] == 3
    assert result["10"]["matches"] == 6
    assert result["10"]["sample_complete"] is False
    assert result["10"]["requested_matches"] == 10
    assert result["15"]["matches"] == 6
    assert result["15"]["sample_complete"] is False
    assert result["15"]["win_percentage"] == 50.0


def test_team_form_match_orients_home_and_away_correctly():
    from football_archive import _team_form_match

    row = {
        "source_key": "match-1",
        "match_date": "2026-10-01",
        "competition_name": "Premier League",
        "home_team": "Arsenal",
        "home_team_key": "arsenal",
        "away_team": "Chelsea",
        "away_team_key": "chelsea",
        "home_score": 1,
        "away_score": 2,
    }
    arsenal = _team_form_match(row, "arsenal")
    chelsea = _team_form_match(row, "chelsea")
    assert (arsenal["result"], arsenal["goals_for"], arsenal["goals_against"], arsenal["venue"]) == ("L", 1, 2, "home")
    assert (chelsea["result"], chelsea["goals_for"], chelsea["goals_against"], chelsea["venue"]) == ("W", 2, 1, "away")


def test_team_form_endpoint_filters_competition_and_kickoff_before_limit(monkeypatch):
    import football_archive

    captured = {"tables": [], "eq": [], "lt": [], "or": []}
    rows = [{
        "source_key": "arsenal-1", "match_date": "2026-10-01",
        "competition_name": "Premier League", "home_team": "Arsenal",
        "home_team_key": "arsenal", "away_team": "Chelsea",
        "away_team_key": "chelsea", "home_score": 2, "away_score": 0,
    }]

    class Query:
        def select(self, *_args, **_kwargs): return self
        def eq(self, column, value): captured["eq"].append((column, value)); return self
        def or_(self, value): captured["or"].append(value); return self
        def lt(self, column, value): captured["lt"].append((column, value)); return self
        def order(self, *_args, **_kwargs): return self
        def limit(self, value): captured.setdefault("limits", []).append(value); return self
        def execute(self): return type("Result", (), {"data": rows})()

    class Client:
        def table(self, name):
            captured["tables"].append(name)
            return Query()

    monkeypatch.setattr(football_archive, "_client_or_503", lambda: Client())
    monkeypatch.setattr(football_archive, "_resolve_team_identity", lambda _client, _code, name: (name.lower(), "exact"))

    result = football_archive.archive_team_recent_form(
        competition="PL",
        home_team="Arsenal",
        away_team="Chelsea",
        kickoff_at="2026-11-07T08:30:00Z",
    )

    assert result["provider_calls"] == 0
    assert result["model_changed"] is False
    assert result["teams"]["home"]["windows"]["5"]["matches"] == 1
    assert result["teams"]["home"]["windows"]["5"]["sample_complete"] is False
    assert captured["tables"] == ["football_match_archive", "football_match_archive"]
    assert captured["lt"] == [("match_date", "2026-11-07"), ("match_date", "2026-11-07")]
    assert captured["limits"] == [15, 15]
    assert captured["eq"].count(("competition_code", "PL")) == 2


def test_market_sample_reports_over_under_btts_and_goal_distribution():
    from football_archive import _summarize_market_sample
    rows = [
        {"home_score": 0, "away_score": 0},
        {"home_score": 1, "away_score": 1},
        {"home_score": 2, "away_score": 1},
        {"home_score": 3, "away_score": 2},
    ]
    result = _summarize_market_sample(rows)
    assert result["sample_size"] == 4
    assert result["markets"]["1_5"]["over"] == {"count": 3, "percentage": 75.0}
    assert result["markets"]["2_5"]["over"] == {"count": 2, "percentage": 50.0}
    assert result["markets"]["3_5"]["over"] == {"count": 1, "percentage": 25.0}
    assert result["markets"]["2_5"]["under"] == {"count": 2, "percentage": 50.0}
    assert result["both_teams_scored"] == {"count": 3, "percentage": 75.0}
    assert result["total_goals_distribution"]["0_1"]["count"] == 1
    assert result["total_goals_distribution"]["2"]["count"] == 1
    assert result["total_goals_distribution"]["3"]["count"] == 1
    assert result["total_goals_distribution"]["4_plus"]["count"] == 1


def test_market_sample_empty_does_not_invent_percentages():
    from football_archive import _summarize_market_sample
    result = _summarize_market_sample([])
    assert result["sample_size"] == 0
    assert result["average_total_goals"] is None
    assert result["markets"]["1_5"]["over"]["percentage"] is None
    assert result["both_teams_scored"]["percentage"] is None


def test_team_form_market_windows_cover_three_goal_lines():
    from football_archive import _summarize_team_form
    matches = [
        {"result": "W", "points": 3, "goals_for": 3, "goals_against": 1, "total_goals": 4, "venue": "home"},
        {"result": "L", "points": 0, "goals_for": 0, "goals_against": 1, "total_goals": 1, "venue": "away"},
        {"result": "D", "points": 1, "goals_for": 1, "goals_against": 1, "total_goals": 2, "venue": "home"},
    ]
    result = _summarize_team_form(matches)["5"]
    assert (result["over_1_5"], result["over_2_5"], result["over_3_5"]) == (2, 1, 1)
    assert result["under_2_5"] == 2
    assert result["sample_complete"] is False


def test_market_patterns_endpoint_applies_competition_and_cutoff_before_limits(monkeypatch):
    import football_archive

    captured = {"eq": [], "lt": [], "limits": [], "tables": []}
    rows = [{
        "source_key": "arsenal-chelsea-1",
        "match_date": "2026-10-01",
        "competition_name": "Premier League",
        "home_team": "Arsenal",
        "home_team_key": "arsenal",
        "away_team": "Chelsea",
        "away_team_key": "chelsea",
        "home_score": 2,
        "away_score": 1,
    }]

    class Query:
        def select(self, *_args, **_kwargs): return self
        def eq(self, column, value): captured["eq"].append((column, value)); return self
        def lt(self, column, value): captured["lt"].append((column, value)); return self
        def or_(self, value): return self
        def order(self, *_args, **_kwargs): return self
        def limit(self, value): captured["limits"].append(value); return self
        def execute(self): return type("Result", (), {"data": rows})()

    class Client:
        def table(self, name):
            captured["tables"].append(name)
            return Query()

    monkeypatch.setattr(football_archive, "_client_or_503", lambda: Client())
    monkeypatch.setattr(
        football_archive, "_resolve_team_identity",
        lambda _client, _code, name: (name.lower(), "exact"),
    )

    result = football_archive.archive_market_patterns(
        competition="PL",
        home_team="Arsenal",
        away_team="Chelsea",
        kickoff_at="2026-11-07T08:30:00Z",
    )

    assert result["provider_calls"] == 0
    assert result["model_changed"] is False
    assert result["competition_sample"]["sample_size"] == 1
    assert result["competition_sample"]["markets"]["2_5"]["over"]["count"] == 1
    assert captured["tables"] == ["football_match_archive"] * 3
    assert captured["eq"].count(("competition_code", "PL")) == 3
    assert captured["lt"] == [("match_date", "2026-11-07")] * 3
    assert captured["limits"] == [1000, 15, 15]
