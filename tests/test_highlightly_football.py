from highlightly_football_client import normalize_name
from football_highlightly_shadow import MODEL_VERSION, predict_highlightly_shadow


def fixture():
    return {"homeTeam":{"id":1,"name":"Alpha"},"awayTeam":{"id":2,"name":"Beta"},
            "league":{"id":99,"name":"Test League","season":2026}}


def stats(team, home=None, away=None):
    return [{"leagueId":99,"season":2026,
             "home":{"games":{"played":10},"goals":{"scored":20,"received":8}},
             "away":{"games":{"played":10},"goals":{"scored":12,"received":15}},
             "total":{"games":{"played":20},"goals":{"scored":32,"received":23}}}]


def recent(team_id, for_goals=2, against=1):
    rows=[]
    for i in range(5):
        rows.append({"date":f"2026-10-{20-i:02d}T15:00:00Z",
                     "homeTeam":{"id":team_id,"name":"Team"},"awayTeam":{"id":9,"name":"Opponent"},
                     "state":{"description":"Finished","score":{"current":f"{for_goals} - {against}"}}})
    return rows


def test_team_name_normalization_handles_accents_and_punctuation():
    assert normalize_name("Atlético-Madrid") == "atletico madrid"


def test_highlightly_shadow_returns_markets_and_stays_experimental():
    result=predict_highlightly_shadow(fixture(),recent(1),recent(2),stats(1),stats(2),[],
                                      "2026-11-04T20:00:00Z")
    assert result["available"] is True
    assert result["model_version"] == MODEL_VERSION
    assert abs(sum(result["probabilities"].values())-1) < 1e-5
    assert result["recommendation"]["status"] == "NO_PLAY_UNTIL_VALIDATED"


def test_missing_team_statistics_does_not_fabricate_prediction():
    result=predict_highlightly_shadow(fixture(),recent(1),recent(2),[],stats(2),[],
                                      "2026-11-04T20:00:00Z")
    assert result["available"] is False


def test_fixture_resolution_requires_exact_teams_and_date(monkeypatch):
    from highlightly_football_client import find_fixture
    import highlightly_football_client as client

    payload = {"data": [
        {"id": 12, "date": "2026-11-04T20:00:00Z",
         "homeTeam": {"name": "Atletico Madrid"}, "awayTeam": {"name": "Real Madrid"}},
        {"id": 13, "date": "2026-11-04T20:00:00Z",
         "homeTeam": {"name": "Atletico Madrid B"}, "awayTeam": {"name": "Real Madrid"}},
    ]}
    monkeypatch.setattr(client, "_get", lambda path, params=None: payload)
    assert find_fixture("2026-11-04", "Atlético-Madrid", "Real Madrid")["id"] == 12


def test_fixture_resolution_rejects_missing_exact_match(monkeypatch):
    import pytest
    import highlightly_football_client as client
    from highlightly_football_client import HighlightlyError, find_fixture

    monkeypatch.setattr(client, "_get", lambda path, params=None: {"data": []})
    with pytest.raises(HighlightlyError) as exc:
        find_fixture("2026-11-04", "Barcelona", "Aston Villa")
    assert exc.value.status_code == 404


def test_fixture_resolution_queries_date_feed_and_matches_provider_names(monkeypatch):
    import highlightly_football_client as client
    from highlightly_football_client import find_fixture

    calls = []
    payload = {"data": [
        {"id": 72221384, "date": "2026-11-07T12:30:00Z",
         "homeTeam": {"name": "Leeds United"}, "awayTeam": {"name": "Tottenham Hotspur"}},
        {"id": 72221385, "date": "2026-11-07T15:00:00Z",
         "homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Hull City"}},
    ]}

    def fake_get(path, params=None):
        calls.append((path, params))
        return payload

    monkeypatch.setattr(client, "_get", fake_get)
    result = find_fixture("2026-11-07", "Leeds United FC", "Tottenham Hotspur FC")

    assert result["id"] == 72221384
    assert calls == [("/matches", {"date": "2026-11-07", "limit": 100, "offset": 0})]


def test_fixture_resolution_reports_date_feed_name_mismatch(monkeypatch):
    import pytest
    import highlightly_football_client as client
    from highlightly_football_client import HighlightlyError, find_fixture

    monkeypatch.setattr(client, "_get", lambda path, params=None: {
        "data": [{"id": 1, "date": "2026-11-08T12:30:00Z",
                  "homeTeam": {"name": "Leeds"}, "awayTeam": {"name": "Tottenham"}}]
    })
    with pytest.raises(HighlightlyError) as exc:
        find_fixture("2026-11-07", "Leeds United FC", "Tottenham Hotspur FC")
    assert exc.value.status_code == 404
    assert "Leeds vs Tottenham" in str(exc.value)


def test_fixture_resolution_scopes_match_query_to_resolved_league_id(monkeypatch):
    import highlightly_football_client as client
    from highlightly_football_client import find_fixture

    calls = []
    countries_payload = [{"code": "GB-ENG", "name": "England"}]
    league_payload = {"data": [
        {"id": 39, "name": "Premier League", "country": {"code": "GB-ENG", "name": "England"}}
    ]}
    match_payload = {"data": [
        {"id": 99, "date": "2026-11-07T12:30:00Z",
         "homeTeam": {"name": "Leeds United"}, "awayTeam": {"name": "Tottenham Hotspur"},
         "league": {"id": 39, "name": "Premier League"}},
        {"id": 100, "date": "2026-11-07T13:00:00Z",
         "homeTeam": {"name": "Leeds United"}, "awayTeam": {"name": "Tottenham Hotspur"},
         "league": {"id": 140, "name": "Other League"}},
    ]}

    def fake_get(path, params=None):
        calls.append((path, params))
        if path == "/countries":
            return countries_payload
        return league_payload if path == "/leagues" else match_payload

    monkeypatch.setattr(client, "_get", fake_get)
    result = find_fixture("2026-11-07", "Leeds United FC", "Tottenham Hotspur FC", "Premier League", "England")

    assert result["id"] == 99
    assert calls == [
        ("/countries", {"name": "England"}),
        ("/leagues", {"leagueName": "Premier League", "limit": 100, "offset": 0, "countryCode": "GB-ENG"}),
        ("/matches", {"date": "2026-11-07", "limit": 100, "offset": 0, "leagueId": 39}),
    ]


def test_fixture_resolution_rejects_ambiguous_same_name_leagues(monkeypatch):
    import pytest
    import highlightly_football_client as client
    from highlightly_football_client import HighlightlyError, find_fixture

    def fake_get(path, params=None):
        if path == "/countries":
            return [{"code": "GB-ENG", "name": "England"}]
        return {"data": [
            {"id": 39, "name": "Premier League", "country": {"code": "GB-ENG", "name": "England"}},
            {"id": 40, "name": "Premier League", "country": {"code": "XX", "name": "Country B"}},
        ]}
    monkeypatch.setattr(client, "_get", fake_get)
    with pytest.raises(HighlightlyError) as exc:
        find_fixture("2026-11-07", "Leeds United", "Tottenham Hotspur", "Premier League")
    assert exc.value.status_code == 409


def test_fixture_resolution_rejects_wrong_league_even_if_team_names_match(monkeypatch):
    import pytest
    import highlightly_football_client as client
    from highlightly_football_client import HighlightlyError, find_fixture

    def fake_get(path, params=None):
        if path == "/countries":
            return [{"code": "GB-ENG", "name": "England"}]
        if path == "/leagues":
            return {"data": [{"id": 39, "name": "Premier League", "country": {"code": "GB-ENG", "name": "England"}}]}
        return {"data": [
            {"id": 99, "date": "2026-11-07T12:30:00Z",
             "homeTeam": {"name": "Leeds United"}, "awayTeam": {"name": "Tottenham Hotspur"},
             "league": {"id": 140, "name": "Other League"}}
        ]}

    monkeypatch.setattr(client, "_get", fake_get)
    with pytest.raises(HighlightlyError) as exc:
        find_fixture("2026-11-07", "Leeds United", "Tottenham Hotspur", "Premier League", "England")
    assert exc.value.status_code == 404
    assert "Other League" in str(exc.value)



def test_fixture_resolution_maps_spain_primera_division_to_la_liga(monkeypatch):
    import highlightly_football_client as client
    from highlightly_football_client import find_fixture

    calls = []

    def fake_get(path, params=None):
        calls.append((path, params))
        if path == "/countries":
            return [{"code": "ES", "name": "Spain"}]
        if path == "/leagues" and "leagueName" in (params or {}):
            # Search results are broad and contain several Spanish competitions.
            return {"data": [
                {"id": 141, "name": "Segunda División", "country": {"code": "ES", "name": "Spain"}},
                {"id": 142, "name": "Primera División Femenina", "country": {"code": "ES", "name": "Spain"}},
                {"id": 140, "name": "La Liga", "country": {"code": "ES", "name": "Spain"}},
            ]}
        if path == "/leagues":
            return {"data": [
                {"id": 141, "name": "Segunda División", "country": {"code": "ES", "name": "Spain"}},
                {"id": 142, "name": "Primera División Femenina", "country": {"code": "ES", "name": "Spain"}},
                {"id": 140, "name": "La Liga", "country": {"code": "ES", "name": "Spain"}},
                {"id": 143, "name": "Copa del Rey", "country": {"code": "ES", "name": "Spain"}},
            ]}
        return {"data": [
            {"id": 88001, "date": "2026-11-07T09:00:00Z",
             "homeTeam": {"name": "Malaga"}, "awayTeam": {"name": "Real Racing Club de Santander"},
             "league": {"id": 140, "name": "La Liga"}}
        ]}

    monkeypatch.setattr(client, "_get", fake_get)
    result = find_fixture(
        "2026-11-07", "Málaga CF", "Real Racing Club de Santander",
        "Primera Division", "Spain",
    )

    assert result["id"] == 88001
    assert calls[-1] == (
        "/matches",
        {"date": "2026-11-07", "limit": 100, "offset": 0, "leagueId": 140},
    )
