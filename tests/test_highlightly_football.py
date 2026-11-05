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
             "homeTeam": {"name": "Malaga"}, "awayTeam": {"name": "Racing Santander"},
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



def test_fixture_resolution_matches_espanyol_and_deportivo_provider_short_names(monkeypatch):
    import highlightly_football_client as client
    from highlightly_football_client import find_fixture

    monkeypatch.setattr(client, "_get", lambda path, params=None: {"data": [
        {"id": 88002, "date": "2026-11-07T11:15:00Z",
         "homeTeam": {"name": "Espanyol"}, "awayTeam": {"name": "Deportivo La Coruña"}}
    ]})

    result = find_fixture(
        "2026-11-07",
        "RCD Espanyol de Barcelona",
        "RC Deportivo La Coruña",
    )

    assert result["id"] == 88002



def test_highlightly_league_catalog_pages_and_preserves_native_names(monkeypatch):
    import highlightly_football_client as client

    calls = []
    def fake_get(path, params=None):
        calls.append((path, params))
        offset = (params or {}).get("offset", 0)
        if offset == 0:
            return {"data": [
                {"id": 10, "name": "Premier League", "country": {"name": "England"}},
                {"id": 11, "name": "Liga MX", "country": {"name": "Mexico"}},
            ], "pagination": {"totalCount": 3}}
        return {"data": [
            {"id": 12, "name": "Primera División", "country": {"name": "Uruguay"}},
            {"id": 11, "name": "Liga MX", "country": {"name": "Mexico"}},
        ], "pagination": {"totalCount": 3}}

    monkeypatch.setattr(client, "_get", fake_get)
    rows = client.get_leagues(page_size=2, max_pages=4)
    assert [row["id"] for row in rows] == [10, 11, 12]
    assert rows[1]["name"] == "Liga MX"
    assert len(calls) == 2
    assert calls[1][1]["offset"] == 2


def test_highlightly_league_matches_use_native_league_id_and_exact_date(monkeypatch):
    import highlightly_football_client as client

    calls = []
    payload = {"data": [
        {"id": 77, "date": "2026-11-07T15:00:00Z", "league": {"id": 500},
         "homeTeam": {"id": 1, "name": "Club Atlético"}, "awayTeam": {"id": 2, "name": "Deportivo"}},
        {"id": 78, "date": "2026-11-08T15:00:00Z", "league": {"id": 500},
         "homeTeam": {"id": 3, "name": "Another"}, "awayTeam": {"id": 4, "name": "Club"}},
        {"id": 79, "date": "2026-11-07T15:00:00Z", "league": {"id": 501},
         "homeTeam": {"id": 5, "name": "Wrong league"}, "awayTeam": {"id": 6, "name": "Other"}},
    ]}
    def fake_get(path, params=None):
        calls.append((path, params))
        return payload
    monkeypatch.setattr(client, "_get", fake_get)
    rows = client.get_league_matches(500, "2026-11-07")
    assert [row["id"] for row in rows] == [77]
    assert calls == [("/matches", {"leagueId": 500, "date": "2026-11-07", "limit": 100, "offset": 0})]


def test_highlightly_fixture_detail_uses_provider_native_match_id(monkeypatch):
    import highlightly_football_client as client

    monkeypatch.setattr(client, "_get", lambda path, params=None: {
        "id": 991, "date": "2026-11-07T15:00:00Z",
        "homeTeam": {"id": 1, "name": "Home"}, "awayTeam": {"id": 2, "name": "Away"},
        "league": {"id": 44, "name": "Native League"},
    })
    row = client.get_fixture(991)
    assert row["id"] == 991
    assert row["league"]["id"] == 44



def test_highlightly_native_analysis_uses_highlightly_id_without_primary_provider(monkeypatch):
    import football_api

    fixture_row = {
        "id": 9001,
        "date": "2099-11-07T15:00:00Z",
        "state": {"description": "Not started"},
        "homeTeam": {"id": 101, "name": "Provider Home"},
        "awayTeam": {"id": 202, "name": "Provider Away"},
        "league": {"id": 303, "name": "Provider League"},
    }
    monkeypatch.setattr(football_api, "get_highlightly_fixture", lambda match_id: fixture_row)
    monkeypatch.setattr(football_api, "get_highlightly_last_five", lambda team_id: [])
    monkeypatch.setattr(football_api, "get_highlightly_team_statistics", lambda team_id, from_date: [])
    monkeypatch.setattr(football_api, "get_highlightly_head_to_head", lambda home_id, away_id: [])
    monkeypatch.setattr(football_api, "predict_highlightly_shadow", lambda *args: {"available": False, "reason": "test"})

    result = football_api.highlightly_native_match_analysis(9001)
    assert result["provider_native"] is True
    assert result["highlightly_match_id"] == 9001
    assert result["fixture_match"]["homeTeam"]["name"] == "Provider Home"


def test_highlightly_rate_limit_sets_cooldown_and_blocks_followup_requests(monkeypatch):
    import highlightly_football_client as client

    class FakeResponse:
        status_code = 429
        headers = {"Retry-After": "90"}
        def json(self):
            return {"message": "rate limit"}

    calls = []
    class FakeRequests:
        @staticmethod
        def get(*args, **kwargs):
            calls.append((args, kwargs))
            return FakeResponse()

    monkeypatch.setenv("HIGHLIGHTLY_API_KEY", "test-key")
    monkeypatch.setattr(client, "requests", FakeRequests)
    monkeypatch.setattr(client, "_rate_limit_until", 0.0)
    monkeypatch.setattr(client, "_rate_limit_message", "Highlightly ha limitado temporalmente las solicitudes.")
    with client._cache_lock:
        client._cache.clear()

    try:
        client._get("/cooldown-test")
        assert False, "Expected HighlightlyError for HTTP 429"
    except client.HighlightlyError as exc:
        assert exc.status_code == 429
        assert "90 segundos" in str(exc)

    try:
        client._get("/cooldown-test-other")
        assert False, "Expected cooldown to block the next request"
    except client.HighlightlyError as exc:
        assert exc.status_code == 429
        assert "bloqueado temporalmente" in str(exc)
    assert len(calls) == 1
    monkeypatch.setattr(client, "_rate_limit_until", 0.0)



def test_highlightly_native_analysis_reuses_fixture_from_league_feed(monkeypatch):
    import football_api

    fixture_row = {
        "id": 9010,
        "date": "2099-11-07T15:00:00Z",
        "state": {"description": "Not started"},
        "homeTeam": {"id": 111, "name": "Native Home"},
        "awayTeam": {"id": 222, "name": "Native Away"},
        "league": {"id": 333, "name": "Native League"},
    }
    monkeypatch.setattr(
        football_api, "get_highlightly_fixture",
        lambda match_id: (_ for _ in ()).throw(AssertionError("No debe consultar el detalle remoto")),
    )
    monkeypatch.setattr(football_api, "get_highlightly_last_five", lambda team_id: [])
    monkeypatch.setattr(football_api, "get_highlightly_team_statistics", lambda team_id, from_date: [])
    monkeypatch.setattr(football_api, "predict_highlightly_shadow", lambda *args: {"available": False, "reason": "test"})

    result = football_api.highlightly_native_match_analysis_from_feed(9010, fixture_row)
    assert result["provider_native"] is True
    assert result["request_optimization"] == "fixture_reused_from_league_feed"
    assert result["fixture_match"]["id"] == 9010


def test_highlightly_native_analysis_rejects_mismatched_fixture_id():
    import pytest
    from fastapi import HTTPException
    import football_api

    with pytest.raises(HTTPException) as exc:
        football_api.highlightly_native_match_analysis_from_feed(9011, {"id": 9010})
    assert exc.value.status_code == 422


def test_highlightly_provider_status_is_read_only(monkeypatch):
    import football_api

    monkeypatch.setattr(football_api, "get_highlightly_provider_status", lambda: {
        "provider": "Highlightly", "state": "quota_exhausted",
        "quota_remaining": 0, "quota_limit": 100, "retry_after_seconds": 120,
    })
    result = football_api.highlightly_provider_status()
    assert result["state"] == "quota_exhausted"
    assert result["quota_remaining"] == 0
    assert result["success"] is True


def test_highlightly_429_distinguishes_exhausted_quota_and_reads_reset(monkeypatch):
    import highlightly_football_client as client

    class FakeResponse:
        status_code = 429
        headers = {
            "x-ratelimit-requests-remaining": "0",
            "x-ratelimit-requests-limit": "100",
            "x-ratelimit-requests-reset": "1800",
        }
        def json(self):
            return {"message": "daily quota exceeded"}

    class FakeRequests:
        @staticmethod
        def get(*args, **kwargs):
            return FakeResponse()

    monkeypatch.setenv("HIGHLIGHTLY_API_KEY", "test-key")
    monkeypatch.setattr(client, "requests", FakeRequests)
    monkeypatch.setattr(client, "_rate_limit_until", 0.0)
    with client._cache_lock:
        client._cache.clear()
        client._provider_status.clear()

    try:
        client._get("/quota-exhausted-test")
        assert False, "Expected HighlightlyError for HTTP 429"
    except client.HighlightlyError as exc:
        assert exc.status_code == 429
        assert "cuota disponible" in str(exc)

    status = client.get_provider_status()
    assert status["state"] == "quota_exhausted"
    assert status["quota_remaining"] == 0
    assert status["quota_limit"] == 100
    assert status["quota_reset_seconds"] == 1800
    assert status["cooldown_active"] is True



def test_persisted_quota_cooldown_is_restored_after_process_restart(monkeypatch):
    from types import SimpleNamespace
    import highlightly_football_client as client

    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def execute(self):
            return SimpleNamespace(data=[{
                "state": {
                    "provider": "Highlightly",
                    "state": "quota_exhausted",
                    "message": "Highlightly indica que se agotó la cuota disponible.",
                    "blocked_until_epoch": int(client.time.time()) + 240,
                }
            }])

    class Store:
        def table(self, _name): return Query()

    monkeypatch.setattr(client, "_quota_store_client", lambda: Store())
    monkeypatch.setattr(client, "_quota_state_loaded", False)
    monkeypatch.setattr(client, "_rate_limit_until", 0.0)
    client._provider_status.clear()

    status = client.get_provider_status()

    assert status["state"] == "quota_exhausted"
    assert status["cooldown_active"] is True
    assert 1 <= status["retry_after_seconds"] <= 240


def test_quota_state_persistence_writes_only_sanitized_diagnostics(monkeypatch):
    import highlightly_football_client as client

    captured = {}

    class Query:
        def upsert(self, payload, **_kwargs):
            captured.update(payload)
            return self
        def execute(self):
            return None

    class Store:
        def table(self, name):
            assert name == "provider_quota_state"
            return Query()

    monkeypatch.setattr(client, "_quota_store_client", lambda: Store())
    with client._cache_lock:
        client._provider_status.clear()
        client._provider_status.update({
            "provider": "Highlightly",
            "state": "quota_exhausted",
            "message": "Quota exhausted",
            "observed_at": 123,
        })

    client._persist_quota_state(456)

    assert captured["provider"] == "Highlightly"
    assert captured["state"]["blocked_until_epoch"] == 456
    assert "api_key" not in str(captured).lower()
    assert "response_body" not in captured["state"]
