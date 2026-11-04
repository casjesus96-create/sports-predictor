from datetime import datetime, timezone

import pytest

import football_stats_client as client


@pytest.fixture(autouse=True)
def reset_cache():
    client.clear_cache()
    yield
    client.clear_cache()


def test_statistics_require_unique_exact_fixture_match(monkeypatch):
    calls = []

    def fake_request(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "fixtures":
            return {"response": [{
                "fixture": {"id": 9981, "date": "2026-10-20T19:00:00+00:00", "status": {"short": "FT"}},
                "teams": {"home": {"name": "Real Madrid"}, "away": {"name": "AC Milan"}},
            }]}
        return {"response": [
            {"team": {"name": "Real Madrid"}, "statistics": [
                {"type": "Corner Kicks", "value": 7},
                {"type": "Yellow Cards", "value": 2},
                {"type": "Ball Possession", "value": "58%"},
            ]},
            {"team": {"name": "AC Milan"}, "statistics": [
                {"type": "Corner Kicks", "value": 3},
                {"type": "Red Cards", "value": 1},
                {"type": "Total Shots", "value": 9},
            ]},
        ]}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.get_completed_match_statistics(
        123, "Real Madrid", "AC Milan", "2026-10-20T19:00:00Z"
    )

    assert result["available"] is True
    assert result["provider_fixture_id"] == 9981
    assert result["home_team"]["statistics"] == {
        "corners": 7, "yellow_cards": 2, "possession": 58,
    }
    assert result["away_team"]["statistics"] == {
        "corners": 3, "red_cards": 1, "shots_total": 9,
    }
    assert len(calls) == 2


def test_statistics_reject_future_match():
    future = datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1)
    with pytest.raises(client.APIFootballError) as exc:
        client.get_completed_match_statistics(
            123, "Real Madrid", "AC Milan", future.isoformat()
        )
    assert exc.value.status_code == 409


def test_statistics_reject_ambiguous_or_unmatched_fixture(monkeypatch):
    monkeypatch.setattr(client, "_request", lambda endpoint, params: {"response": []})
    with pytest.raises(client.APIFootballError) as exc:
        client.get_completed_match_statistics(
            123, "Real Madrid", "AC Milan", "2026-10-20T19:00:00Z"
        )
    assert exc.value.status_code == 404


def test_api_key_is_required(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    with pytest.raises(client.APIFootballError) as exc:
        client._request("fixtures", {"date": "2026-10-20"})
    assert exc.value.status_code == 503
