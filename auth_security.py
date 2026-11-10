"""Private, single-administrator authentication backed by Supabase Auth.

Secrets are supplied only through the deployment environment. This module
never stores passwords or Supabase tokens in the repository/database.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests

_CACHE_TTL_SECONDS = 20
_VALIDATED_TOKENS: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_REQUEST_TIMEOUT = 8


class AuthConfigurationError(RuntimeError):
    pass


class AuthProviderError(RuntimeError):
    pass


def _configuration() -> tuple[str, str, str]:
    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    admin_email = os.getenv("SPORTS_PREDICTOR_ADMIN_EMAIL", "").strip().casefold()
    if not base_url or not anon_key or not admin_email:
        raise AuthConfigurationError(
            "Configura SUPABASE_URL, SUPABASE_ANON_KEY y "
            "SPORTS_PREDICTOR_ADMIN_EMAIL en el entorno del servidor."
        )
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AuthConfigurationError("SUPABASE_URL debe ser una URL HTTPS válida.")
    if "@" not in admin_email or len(admin_email) > 254:
        raise AuthConfigurationError("SPORTS_PREDICTOR_ADMIN_EMAIL no es válido.")
    return base_url, anon_key, admin_email


def _auth_request(method: str, path: str, *, token: str | None = None,
                  payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    base_url, anon_key, _ = _configuration()
    headers = {"apikey": anon_key, "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.request(
            method,
            f"{base_url}/auth/v1/{path.lstrip('/')}",
            headers=headers,
            json=payload,
            timeout=_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise AuthProviderError("El servicio de autenticación no está disponible.") from exc
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    if response.status_code >= 500:
        raise AuthProviderError("El servicio de autenticación no está disponible.")
    return response.status_code, data if isinstance(data, dict) else {}


def is_admin_email(email: str | None) -> bool:
    if not email:
        return False
    _, _, admin_email = _configuration()
    return email.strip().casefold() == admin_email


def sign_in(email: str, password: str) -> dict[str, Any] | None:
    if not isinstance(email, str) or not isinstance(password, str):
        return None
    if not email.strip() or not password or len(password) > 1024:
        return None
    status, data = _auth_request(
        "POST",
        "token?grant_type=password",
        payload={"email": email.strip(), "password": password},
    )
    if status != 200:
        return None
    user = data.get("user") or {}
    if not is_admin_email(user.get("email")):
        return None
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if not access_token or not refresh_token:
        return None
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": max(60, min(int(data.get("expires_in") or 3600), 86400)),
        "email": user.get("email"),
    }


def refresh_session(refresh_token: str) -> dict[str, Any] | None:
    if not refresh_token:
        return None
    status, data = _auth_request(
        "POST",
        "token?grant_type=refresh_token",
        payload={"refresh_token": refresh_token},
    )
    if status != 200:
        return None
    user = data.get("user") or {}
    if not is_admin_email(user.get("email")):
        return None
    access_token = data.get("access_token")
    next_refresh_token = data.get("refresh_token")
    if not access_token or not next_refresh_token:
        return None
    return {
        "access_token": access_token,
        "refresh_token": next_refresh_token,
        "expires_in": max(60, min(int(data.get("expires_in") or 3600), 86400)),
        "email": user.get("email"),
    }


def validate_access_token(access_token: str) -> dict[str, Any] | None:
    if not access_token or len(access_token) > 8192:
        return None
    digest = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _VALIDATED_TOKENS.get(digest)
        if cached and cached[0] > now:
            return dict(cached[1])
        _VALIDATED_TOKENS.pop(digest, None)

    status, user = _auth_request("GET", "user", token=access_token)
    if status != 200 or not is_admin_email(user.get("email")):
        return None

    with _CACHE_LOCK:
        _VALIDATED_TOKENS[digest] = (now + _CACHE_TTL_SECONDS, dict(user))
        if len(_VALIDATED_TOKENS) > 2048:
            expired = [key for key, value in _VALIDATED_TOKENS.items() if value[0] <= now]
            for key in expired:
                _VALIDATED_TOKENS.pop(key, None)
            if len(_VALIDATED_TOKENS) > 2048:
                _VALIDATED_TOKENS.clear()
    return user


def revoke_session(access_token: str | None) -> None:
    if not access_token:
        return
    try:
        _auth_request("POST", "logout", token=access_token)
    finally:
        digest = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
        with _CACHE_LOCK:
            _VALIDATED_TOKENS.pop(digest, None)


def clear_validation_cache() -> None:
    """Test helper; does not affect active Supabase sessions."""
    with _CACHE_LOCK:
        _VALIDATED_TOKENS.clear()
