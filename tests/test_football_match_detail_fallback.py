from unittest.mock import Mock

import football_data_client


def test_get_match_uses_individual_endpoint_and_cache(monkeypatch):
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-token")
    football_data_client.clear_cache()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"match": {"id": 123, "status": "FINISHED"}}
    request = Mock(return_value=response)
    monkeypatch.setattr(football_data_client.requests, "get", request)

    first = football_data_client.get_match(123)
    second = football_data_client.get_match(123)

    assert first == second == {"match": {"id": 123, "status": "FINISHED"}}
    assert request.call_count == 1
    assert request.call_args.args[0].endswith("/matches/123")
    football_data_client.clear_cache()


def test_get_match_rejects_invalid_id():
    try:
        football_data_client.get_match(0)
    except football_data_client.FootballDataError as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected invalid match ID to be rejected")
