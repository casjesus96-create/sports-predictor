from fastapi.testclient import TestClient

import main


def test_private_api_rejects_requests_without_session():
    client = TestClient(main.app)
    response = client.get("/api/v1/nfl/games")
    assert response.status_code == 401
    assert response.json()["detail"] == "Autenticación requerida."
    assert response.headers["cache-control"] == "no-store"


def test_private_api_requires_second_factor(monkeypatch):
    monkeypatch.setattr(main, "validate_access_token", lambda token: {"email": "owner@example.com"})
    monkeypatch.setattr(main, "token_assurance_level", lambda token: "aal1")
    client = TestClient(main.app)
    response = client.get(
        "/api/v1/nfl/games",
        cookies={"sp_access_token": "password-only-session"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "MFA_REQUIRED"


def test_private_api_passes_mfa_session_to_route(monkeypatch):
    monkeypatch.setattr(main, "validate_access_token", lambda token: {"email": "owner@example.com"})
    monkeypatch.setattr(main, "token_assurance_level", lambda token: "aal2")
    client = TestClient(main.app)
    response = client.get(
        "/api/v1/route-that-does-not-exist",
        cookies={"sp_access_token": "mfa-session"},
    )
    assert response.status_code == 404


def test_health_endpoint_remains_public_and_has_security_headers():
    client = TestClient(main.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_openapi_schema_is_private():
    client = TestClient(main.app)
    response = client.get("/openapi.json")
    assert response.status_code == 401
