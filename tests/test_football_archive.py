from football_archive import (
    build_match_payload,
    normalize_team_key,
    parse_csv_matches,
    season_code,
)


def test_team_key_normalizes_accents_and_club_suffixes():
    assert normalize_team_key("Arsenal FC") == "arsenal"
    assert normalize_team_key("Málaga CF") == "malaga"
    assert normalize_team_key("Hull City AFC") == "hull city"
    assert normalize_team_key("Manchester Utd") == "manchester united"
    assert normalize_team_key("Man City") == "manchester city"
    assert normalize_team_key("Spurs") == "tottenham hotspur"


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
