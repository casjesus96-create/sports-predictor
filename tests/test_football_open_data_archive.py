from football_open_data_archive import (
    OPENFOOTBALL_COMPETITIONS,
    _source_url,
    parse_openfootball_matches,
)


def test_openfootball_source_paths_are_explicit_and_distinct():
    assert _source_url("PT1", 2024).endswith("/portugal/2024-25_pt1.txt")
    assert _source_url("NL1", 2024).endswith("/netherlands/2024-25_nl1.txt")
    assert _source_url("UCL", 2024).endswith("/2024-25/cl.txt")
    assert _source_url("BR1", 2024).endswith("/brazil/2024_br1.txt")
    assert set(OPENFOOTBALL_COMPETITIONS) == {"PT1", "NL1", "UCL", "BR1"}


def test_parser_imports_only_completed_matches_and_strips_country_tags():
    source = """= UEFA Champions League 2024/25

  Tue Sep 17 2024
    18:45  BSC Young Boys (SUI)    v Aston Villa FC (ENG)     0-3 (0-2)
           Juventus FC (ITA)       v PSV (NED)                3-1 (2-0)
           Unplayed FC (ENG)       v Future FC (ESP)

"""
    rows = parse_openfootball_matches(source, "UCL", 2024)

    assert len(rows) == 2
    assert rows[0]["match_date"] == "2024-09-17"
    assert rows[0]["home_team"] == "BSC Young Boys"
    assert rows[0]["away_team"] == "Aston Villa FC"
    assert (rows[0]["home_score"], rows[0]["away_score"]) == (0, 3)
    assert rows[0]["result"] == "A"
    assert rows[0]["source"] == "openfootball"
    assert rows[0]["competition_code"] == "UCL"
    assert len(rows[0]["source_key"]) == 64


def test_parser_infers_year_rollover_for_season_without_repeated_year():
    source = """  Fri Dec 20 2024
    20:00  Winter FC v Snow FC 1-0

  Sat Jan 4
    15:00  Spring FC v Summer FC 2-2
"""
    rows = parse_openfootball_matches(source, "NL1", 2024)

    assert [row["match_date"] for row in rows] == ["2024-12-20", "2025-01-04"]


def test_parser_rejects_unknown_competition_and_invalid_scores():
    import pytest

    with pytest.raises(ValueError):
        parse_openfootball_matches("  Tue Sep 17 2024\n", "BAD", 2024)

    source = """  Tue Sep 17 2024
    18:45  Team A v Team B 31-0
    20:00  Team C v Team D 1-0
"""
    rows = parse_openfootball_matches(source, "PT1", 2024)
    assert len(rows) == 1
    assert (rows[0]["home_score"], rows[0]["away_score"]) == (1, 0)
