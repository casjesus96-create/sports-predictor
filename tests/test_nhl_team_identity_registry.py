import pytest

from nhl_team_identity_registry import (
    REGISTRY_VERSION,
    build_season_team_identity_map,
    get_registry_entries,
    resolve_team_identity,
)


def test_registry_has_a_version_and_current_team_codes_are_season_scoped():
    assert REGISTRY_VERSION
    assert resolve_team_identity("2024-2025", "UTA") == "UTA"
    assert resolve_team_identity("2023-2024", "UTA") is None
    assert resolve_team_identity("2020-2021", "SEA") is None
    assert resolve_team_identity("2021-2022", "SEA") == "SEA"


@pytest.mark.parametrize(
    ("season", "abbreviation", "expected"),
    [
        ("1979-1980", "AEM", "CGY"),
        ("1979-1980", "HFD", "CAR"),
        ("1994-1995", "QUE", "COL"),
        ("1992-1993", "MNS", "DAL"),
        ("1995-1996", "WIN", "WPG"),
        ("1996-1997", "PHX", "ARI"),
        ("2013-2014", "PHX", "ARI"),
        ("2014-2015", "ARI", "ARI"),
        ("2010-2011", "ATL", "WPG"),
        ("2011-2012", "WPG", "WPG"),
        ("1917-1918", "TAN", "TOR"),
        ("1924-1925", "TSP", "TOR"),
        ("1926-1927", "DCG", "DET"),
        ("1930-1931", "DFL", "DET"),
        ("1919-1920", "QBD", "NYA"),
        ("1924-1925", "HAM", "NYA"),
        ("1941-1942", "BRK", "NYA"),
        ("1930-1931", "QUA", "PIR"),
        ("1934-1935", "SLE", "SEN"),
        ("1967-1968", "OAK", "DAL"),
        ("1975-1976", "CGS", "DAL"),
        ("1977-1978", "CLE", "DAL"),
        ("1974-1975", "KCS", "NJD"),
        ("1981-1982", "CLR", "NJD"),
    ],
)
def test_historical_statistical_lineage_by_season(season, abbreviation, expected):
    assert resolve_team_identity(season, abbreviation) == expected


def test_historical_abbreviation_is_rejected_outside_its_valid_period():
    assert resolve_team_identity("1997-1998", "WIN") is None
    assert resolve_team_identity("2014-2015", "PHX") is None
    assert resolve_team_identity("2024-2025", "ARI") is None
    assert resolve_team_identity("1995-1996", "HFD") == "CAR"
    assert resolve_team_identity("1942-1943", "BRK") is None
    assert resolve_team_identity("1978-1979", "CLE") is None
    assert resolve_team_identity("1982-1983", "CLR") is None


def test_build_map_only_returns_codes_valid_in_requested_season():
    mapping = build_season_team_identity_map(
        "1996-1997",
        ["HFD", "PHX", "QUE", "WIN", "ATL", "WPG", "UTA", "UNKNOWN"],
    )
    assert mapping == {"HFD": "CAR", "PHX": "ARI"}


def test_registry_entries_are_filtered_and_returned_as_copies():
    entries = get_registry_entries("2024-2025")
    assert any(row["abbreviation"] == "UTA" for row in entries)
    assert not any(row["abbreviation"] == "ARI" for row in entries)
    entries[0]["canonical_key"] = "CORRUPTED"
    assert get_registry_entries("2024-2025")[0]["canonical_key"] != "CORRUPTED"


@pytest.mark.parametrize("invalid_season", ["20252026", "2025-2027", "bad"])
def test_rejects_invalid_season_format(invalid_season):
    with pytest.raises(ValueError):
        resolve_team_identity(invalid_season, "TOR")
