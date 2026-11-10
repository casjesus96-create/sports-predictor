import base64
import json

import pytest

import auth_security


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "public-anon-key")
    monkeypatch.setenv("SPORTS_PREDICTOR_ADMIN_EMAIL", "owner@example.com")
    auth_security.clear_validation_cache()


def _jwt(aal="aal2"):
    payload = base64.urlsafe_b64encode(
        json.dumps({"aal": aal}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_sign_in_returns_session_only_for_allowlisted_admin(auth_env, monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse(200, {
            "access_token": "owner-access",
            "refresh_token": "owner-refresh",
            "expires_in": 3600,
            "user": {"email": "OWNER@example.com"},
        })

    monkeypatch.setattr(auth_security.requests, "request", fake_request)
    result = auth_security.sign_in("owner@example.com", "strong-password")
    assert result["access_token"] == "owner-access"
    assert result["email"] == "OWNER@example.com"
    assert calls[0][1].endswith("/token?grant_type=password")


def test_sign_in_revokes_non_allowlisted_account(auth_env, monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        if "grant_type=password" in url:
            return FakeResponse(200, {
                "access_token": "other-access",
                "refresh_token": "other-refresh",
                "user": {"email": "intruder@example.com"},
            })
        return FakeResponse(204, {})

    monkeypatch.setattr(auth_security.requests, "request", fake_request)
    assert auth_security.sign_in("intruder@example.com", "password") is None
    assert len(calls) == 2
    assert calls[1][1].endswith("/logout")


def test_validate_access_token_uses_short_lived_cache(auth_env, monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(url)
        return FakeResponse(200, {"email": "owner@example.com", "factors": []})

    monkeypatch.setattr(auth_security.requests, "request", fake_request)
    assert auth_security.validate_access_token("valid-access")["email"] == "owner@example.com"
    assert auth_security.validate_access_token("valid-access")["email"] == "owner@example.com"
    assert len(calls) == 1


def test_validate_access_token_rejects_non_admin(auth_env, monkeypatch):
    monkeypatch.setattr(
        auth_security.requests,
        "request",
        lambda *args, **kwargs: FakeResponse(200, {"email": "other@example.com"}),
    )
    assert auth_security.validate_access_token("other-access") is None


def test_auth_configuration_fails_closed_when_required_values_missing(monkeypatch):
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SPORTS_PREDICTOR_ADMIN_EMAIL", "owner@example.com")
    with pytest.raises(auth_security.AuthConfigurationError):
        auth_security.sign_in("owner@example.com", "password")


def test_totp_verification_requires_valid_six_digit_code(auth_env, monkeypatch):
    monkeypatch.setattr(
        auth_security.requests,
        "request",
        lambda *args, **kwargs: pytest.fail("Invalid OTP must not call Supabase"),
    )
    assert auth_security.verify_totp("access", "factor", "123") is None
    assert auth_security.verify_totp("access", "factor", "12ab56") is None


def test_totp_verification_returns_only_aal2_session(auth_env, monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/challenge"):
            return FakeResponse(200, {"id": "challenge-1"})
        return FakeResponse(200, {
            "access_token": _jwt("aal2"),
            "refresh_token": "rotated-refresh",
            "expires_in": 3600,
            "user": {"email": "owner@example.com"},
        })

    monkeypatch.setattr(auth_security.requests, "request", fake_request)
    session = auth_security.verify_totp("password-session", "factor-1", "123456")
    assert session["refresh_token"] == "rotated-refresh"
    assert auth_security.token_assurance_level(session["access_token"]) == "aal2"
    assert len(calls) == 2
    assert calls[0][1].endswith("/factors/factor-1/challenge")
    assert calls[1][2]["json"]["code"] == "123456"


def test_aal_claim_is_not_accepted_from_malformed_token():
    assert auth_security.token_assurance_level("not-a-jwt") == "aal0"
