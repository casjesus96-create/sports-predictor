"""Secure, rate-limit-aware client for football-data.org v4.

The API token is read only from FOOTBALL_DATA_API_KEY on the server.
A small process-local TTL cache avoids unnecessary calls on the free tier.
"""
from __future__ import annotations

import os
import time
from threading import Lock
from typing import Any

import requests


BASE_URL = "https://api.football-data.org/v4"
REQUEST_TIMEOUT_SECONDS = 12
CACHE_TTL_SECONDS = 60
LEAGUES = {
    "PL": {"name": "Premier League", "country": "England"},
    "PD": {"name": "LaLiga", "country": "Spain"},
    "SA": {"name": "Serie A", "country": "Italy"},
    "BL1": {"name": "Bundesliga", "country": "Germany"},
    "FL1": {"name": "Ligue 1", "country": "France"},
    "DED": {"name": "Eredivisie", "country": "Netherlands"},
    "PPL": {"name": "Primeira Liga", "country": "Portugal"},
    "BSA": {"name": "Brasileirão Série A", "country": "Brazil"},
    "CL": {"name": "UEFA Champions League", "country": "Europe"},
}

_cache: dict[tuple, tuple[float, Any]] = {}
_cache_lock = Lock()


class FootballDataError(RuntimeError):
    """Sanitized upstream error safe to return to API consumers."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _token() -> str:
    token = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
    if not token:
        raise FootballDataError(
            "Falta configurar FOOTBALL_DATA_API_KEY en el entorno del backend.",
            503,
        )
    return token


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _token()
    clean_params = tuple(sorted(
        (str(key), str(value)) for key, value in (params or {}).items()
        if value is not None
    ))
    cache_key = (path, clean_params)
    now = time.monotonic()

    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

    try:
        response = requests.get(
            f"{BASE_URL}{path}",
            headers={"X-Auth-Token": token, "Accept": "application/json"},
            params=dict(clean_params),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise FootballDataError("No fue posible conectar con football-data.org.") from exc

    if response.status_code == 429:
        raise FootballDataError(
            "Se alcanzó el límite de solicitudes de football-data.org. Intenta más tarde.",
            429,
        )
    if response.status_code in (401, 403):
        raise FootballDataError(
            "football-data.org rechazó la credencial o el plan no permite este recurso.",
            502,
        )
    if response.status_code >= 500:
        raise FootballDataError("football-data.org presenta un error temporal.")
    if response.status_code >= 400:
        raise FootballDataError(
            f"football-data.org rechazó la consulta (HTTP {response.status_code}).",
            502,
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise FootballDataError("football-data.org devolvió una respuesta no válida.") from exc

    with _cache_lock:
        _cache[cache_key] = (time.monotonic() + CACHE_TTL_SECONDS, data)
    return data


def get_competitions() -> list[dict[str, Any]]:
    data = _get("/competitions")
    available = {
        item.get("code"): item
        for item in data.get("competitions", [])
        if item.get("code")
    }
    result = []
    for code, config in LEAGUES.items():
        item = available.get(code)
        result.append({
            "code": code,
            "name": config["name"],
            "country": config["country"],
            "available_in_plan": item is not None,
            "provider_id": item.get("id") if item else None,
            "provider_name": item.get("name") if item else None,
            "current_season": item.get("currentSeason") if item else None,
        })
    return result


def get_matches(
    competition: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    code = competition.strip().upper()
    if code not in LEAGUES:
        raise FootballDataError(
            f"Competición no admitida. Usa uno de estos códigos: {', '.join(LEAGUES)}.",
            400,
        )
    params = {"dateFrom": date_from, "dateTo": date_to}
    return _get(f"/competitions/{code}/matches", params)


def get_match(match_id: int) -> dict[str, Any]:
    """Fetch one provider match; cached to avoid repeat calls for the same ID."""
    if isinstance(match_id, bool) or not isinstance(match_id, int) or match_id <= 0:
        raise FootballDataError("Identificador de partido no válido.", 400)
    return _get(f"/matches/{match_id}")


def get_standings(competition: str) -> dict[str, Any]:
    code = competition.strip().upper()
    if code not in LEAGUES:
        raise FootballDataError(
            f"Competición no admitida. Usa uno de estos códigos: {', '.join(LEAGUES)}.",
            400,
        )
    return _get(f"/competitions/{code}/standings")


def clear_cache() -> None:
    """Clear process-local cache; primarily useful for deterministic tests."""
    with _cache_lock:
        _cache.clear()
