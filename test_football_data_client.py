import os
from unittest.mock import Mock

import pytest
import requests

import football_data_client as client
from football_data_client import FootballDataError


@pytest.fixture(autouse=True)
def reset_client(monkeypatch):
    client.clear_cache()
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-token")
    yield
    client.clear_cache()


def test_token_missing_fails_without_network(monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    monkeypatch.setattr(client.requests, "get", Mock(side_effect=AssertionError("network called")))
    with pytest.raises(FootballDataError) as error:
        client.get_competitions()
    assert error.value.status_code == 503


def test_competitions_reports_only_provider_available_codes(monkeypatch):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "competitions": [
            {"id": 2021, "name": "Premier League", "code": "PL",
             "currentSeason": {"startDate": "2026-08-01"}},
            {"id": 2014, "name": "Primera Division", "code": "PD"},
        ]
    }
    request = Mock(return_value=response)
    monkeypatch.setattr(client.requests, "get", request)

    result = client.get_competitions()
    assert result[0]["available_in_plan"] is True
    assert result[0]["provider_id"] == 2021
    assert result[1]["available_in_plan"] is True
    assert result[2]["available_in_plan"] is False
    assert request.call_count == 1
    assert request.call_args.kwargs["headers"]["X-Auth-Token"] == "test-token"


def test_competitions_cache_reduces_calls(monkeypatch):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"competitions": []}
    request = Mock(return_value=response)
    monkeypatch.setattr(client.requests, "get", request)

    client.get_competitions()
    client.get_competitions()
    assert request.call_count == 1


def test_429_is_mapped_to_rate_limit_error(monkeypatch):
    response = Mock()
    response.status_code = 429
    monkeypatch.setattr(client.requests, "get", Mock(return_value=response))
    with pytest.raises(FootballDataError) as error:
        client.get_competitions()
    assert error.value.status_code == 429


def test_invalid_competition_is_rejected_before_network(monkeypatch):
    monkeypatch.setattr(client.requests, "get", Mock(side_effect=AssertionError("network called")))
    with pytest.raises(FootballDataError) as error:
        client.get_matches("FAKE")
    assert error.value.status_code == 400


def test_network_failure_is_sanitized(monkeypatch):
    monkeypatch.setattr(
        client.requests, "get",
        Mock(side_effect=requests.Timeout("contains no token")),
    )
    with pytest.raises(FootballDataError) as error:
        client.get_competitions()
    assert "token" not in str(error.value).lower()
