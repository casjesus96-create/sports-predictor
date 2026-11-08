import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from football_archive import (
    AppFinalizedMatchRequest,
    _build_app_finalized_payload,
    archive_ingest_app_finalized_match,
    create_app_finalized_verification_token,
)


@pytest.fixture(autouse=True)
def _signing_secret(monkeypatch):
    monkeypatch.setenv("FOOTBALL_ARCHIVE_SIGNING_SECRET", "unit-test-signing-secret")


def _request(**overrides):
    values = {
        "match_id": 123456,
        "competition_code": "PL",
        "status": "FINISHED",
        "utc_date": "2026-11-07T20:00:00Z",
        "home_team": "Arsenal FC",
        "away_team": "Chelsea FC",
        "home_score": 2,
        "away_score": 1,
    }
    values.update(overrides)
    if "verification_token" not in values:
        values["verification_token"] = create_app_finalized_verification_token(values)
    return AppFinalizedMatchRequest(**values)


class _Query:
    def __init__(self, table, key):
        self.table_name = table
        self.filters = {}
        self.key = key

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, _value):
        return self

    def execute(self):
        if self.table_name == "football_team_aliases":
            return type("Result", (), {"data": []})()
        if self.table_name == "football_archive_teams":
            requested_key = self.filters.get("canonical_team_key")
            resolved_key = requested_key if self.key is None else self.key
            rows = [{"canonical_team_key": resolved_key}] if requested_key == resolved_key else []
            return type("Result", (), {"data": rows})()
        raise AssertionError(f"Unexpected table: {self.table_name}")


class _Client:
    def table(self, name):
        return _Query(name, None)


def test_app_finalized_payload_requires_confirmed_teams_and_uses_archive_identity():
    payload = _build_app_finalized_payload(_request(), _Client())

    assert payload["source"] == "APP_FINALIZED"
    assert payload["competition_code"] == "PL"
    assert payload["season"] == "2627"
    assert payload["home_team_key"] == "arsenal"
    assert payload["away_team_key"] == "chelsea"
    assert payload["home_score"] == 2
    assert payload["away_score"] == 1
    assert payload["result"] == "H"
    assert len(payload["source_key"]) == 64
    assert payload["source_key"] == _build_app_finalized_payload(_request(), _Client())["source_key"]


@pytest.mark.parametrize("overrides", [
    {"status": "IN_PLAY"},
    {"status": "AWARDED"},
    {"utc_date": "2026-11-07T20:00:00.000"},
    {"utc_date": "2026-11-09T20:00:00Z"},
    {"home_score": -1},
    {"away_score": 31},
])
def test_app_finalized_payload_rejects_nonfinal_or_invalid_match_data(overrides):
    # Pydantic rejects impossible score values while constructing the request;
    # semantic fixture checks (status/date) are rejected by the payload builder.
    with pytest.raises((HTTPException, ValidationError)):
        request = _request(**overrides)
        _build_app_finalized_payload(request, _Client())


def test_app_finalized_request_rejects_boolean_scores():
    with pytest.raises(ValidationError):
        _request(home_score=True)


def test_app_finalized_payload_rejects_unknown_team_instead_of_fuzzy_matching():
    class UnknownClient(_Client):
        def table(self, name):
            return _Query(name, "not-the-requested-team")

    with pytest.raises(HTTPException) as exc:
        _build_app_finalized_payload(_request(), UnknownClient())
    assert exc.value.status_code == 409


@pytest.mark.parametrize("rpc_status,expected_inserted,expected_present", [
    ("INSERTED", True, False),
    ("ALREADY_PRESENT", False, True),
])
def test_app_finalized_endpoint_returns_idempotent_rpc_outcome(
    monkeypatch, rpc_status, expected_inserted, expected_present
):
    import football_archive

    class RpcClient(_Client):
        def rpc(self, name, params):
            assert name == "ingest_app_finalized_football_match"
            assert params["p_external_match_id"] == "123456"
            assert params["p_match"]["source"] == "APP_FINALIZED"
            return type("Rpc", (), {
                "execute": lambda self: type("Result", (), {
                    "data": [{"status": rpc_status, "source_key": params["p_match"]["source_key"]}]
                })()
            })()

    monkeypatch.setattr(football_archive, "_client_or_503", lambda: RpcClient())
    result = archive_ingest_app_finalized_match(_request())

    assert result["success"] is True
    assert result["inserted"] is expected_inserted
    assert result["already_present"] is expected_present
    assert result["model_changed"] is False
    assert result["provider_calls"] == 0


def test_app_finalized_endpoint_rejects_conflicting_existing_result(monkeypatch):
    import football_archive

    class RpcClient(_Client):
        def rpc(self, _name, _params):
            return type("Rpc", (), {
                "execute": lambda self: type("Result", (), {
                    "data": [{"status": "CONFLICT", "source_key": "existing-key"}]
                })()
            })()

    monkeypatch.setattr(football_archive, "_client_or_503", lambda: RpcClient())
    with pytest.raises(HTTPException) as exc:
        archive_ingest_app_finalized_match(_request())
    assert exc.value.status_code == 409


def test_app_finalized_date_uses_competition_local_calendar_day():
    payload = _build_app_finalized_payload(
        _request(utc_date="2026-07-01T23:30:00Z"),
        _Client(),
    )
    # 23:30 UTC is 00:30 on July 2 in London during British Summer Time.
    assert payload["match_date"] == "2026-07-02"
    assert payload["season"] == "2627"


def test_app_finalized_payload_rejects_tampered_provider_score():
    request = _request()
    request.home_score = 3
    with pytest.raises(HTTPException) as exc:
        _build_app_finalized_payload(request, _Client())
    assert exc.value.status_code == 403
