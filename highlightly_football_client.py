"""Highlightly direct Football API client with bounded cache and sanitized errors."""
from __future__ import annotations

import os
import time
import unicodedata
from threading import Lock
from typing import Any

import requests

BASE_URL = "https://soccer.highlightly.net"
TIMEOUT_SECONDS = 10
CACHE_TTLS = {
    "/matches": 300,
    "/statistics/": 300,
    "/last-five-games": 1800,
    "/head-2-head": 3600,
    "/teams/statistics/": 3600,
}
_cache: dict[tuple, tuple[float, Any]] = {}
_cache_lock = Lock()


class HighlightlyError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _key() -> str:
    value = os.getenv("HIGHLIGHTLY_API_KEY", "").strip()
    if not value:
        raise HighlightlyError("Falta configurar HIGHLIGHTLY_API_KEY en el backend de Render.", 503)
    return value


def _ttl(path: str) -> int:
    for prefix, ttl in CACHE_TTLS.items():
        if path == prefix or path.startswith(prefix):
            return ttl
    return 300


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    token = _key()
    clean = tuple(sorted((str(k), str(v)) for k, v in (params or {}).items() if v is not None))
    cache_key = (path, clean)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
    try:
        response = requests.get(
            f"{BASE_URL}{path}",
            headers={"x-rapidapi-key": token, "Accept": "application/json"},
            params=dict(clean),
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise HighlightlyError("No fue posible conectar con Highlightly.") from exc
    if response.status_code == 401:
        raise HighlightlyError("Highlightly rechazó la clave configurada (HTTP 401). Revisa HIGHLIGHTLY_API_KEY en Render.", 502)
    if response.status_code == 403:
        raise HighlightlyError("Highlightly rechazó la solicitud o el acceso al recurso (HTTP 403).", 502)
    if response.status_code == 429:
        raise HighlightlyError("Se alcanzó el límite de solicitudes de Highlightly. Intenta más tarde.", 429)
    if response.status_code == 404:
        raise HighlightlyError("Highlightly no encontró datos para este encuentro o recurso.", 404)
    if response.status_code >= 500:
        raise HighlightlyError("Highlightly presenta un error temporal.")
    if response.status_code >= 400:
        raise HighlightlyError(f"Highlightly rechazó la consulta (HTTP {response.status_code}).")
    try:
        data = response.json()
    except ValueError as exc:
        raise HighlightlyError("Highlightly devolvió una respuesta JSON no válida.") from exc
    with _cache_lock:
        _cache[cache_key] = (time.monotonic() + _ttl(path), data)
    return data


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    tokens = "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
    ignored = {"fc", "cf", "afc", "sc", "ac", "cd", "ud", "sd", "fk", "sk", "de", "the"}
    return " ".join(token for token in tokens if token not in ignored)


def find_fixture(date: str, home_name: str, away_name: str, league_name: str | None = None) -> dict:
    """Resolve a fixture from the UTC date feed, then verify both teams locally.

    Do not send provider-specific team-name filters: their exact matching rules
    can differ from football-data.org naming (for example, suffixes such as FC).
    A date-only request is bounded to one calendar day and keeps discovery to
    one quota unit; identity is verified against the returned records below.
    """
    params = {
        "date": date,
        "limit": 100,
        "offset": 0,
    }
    if league_name and str(league_name).strip():
        params["leagueName"] = str(league_name).strip()
    payload = _get("/matches", params)
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise HighlightlyError("Highlightly devolvió un formato inesperado al buscar el partido.")

    expected_home = normalize_name(home_name)
    expected_away = normalize_name(away_name)
    if not expected_home or not expected_away:
        raise HighlightlyError("No se pudieron normalizar los nombres de los equipos.", 422)

    matches = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        home_data = row.get("homeTeam") or {}
        away_data = row.get("awayTeam") or {}
        home = normalize_name(home_data.get("name", ""))
        away = normalize_name(away_data.get("name", ""))
        kickoff = str(row.get("date") or "")
        if (
            home == expected_home
            and away == expected_away
            and kickoff[:10] == date
            and isinstance(row.get("id"), int)
        ):
            matches.append(row)

    if len(matches) != 1:
        if not matches:
            # Include a small, sanitized diagnostic to distinguish an empty
            # date feed from a team-name mismatch without exposing credentials.
            same_day = [
                f"{(row.get('homeTeam') or {}).get('name', '?')} vs "
                f"{(row.get('awayTeam') or {}).get('name', '?')}"
                for row in rows if isinstance(row, dict)
            ][:8]
            if same_day:
                raise HighlightlyError(
                    "Highlightly devolvió partidos para la fecha, pero los nombres "
                    f"no coincidieron exactamente. Partidos recibidos: {'; '.join(same_day)}",
                    404,
                )
            raise HighlightlyError(
                "Highlightly no devolvió partidos para la fecha solicitada.",
                404,
            )
        raise HighlightlyError(
            "Highlightly devolvió más de una coincidencia exacta; se requiere revisión manual.",
            409,
        )
    return matches[0]

def get_match_statistics(match_id: int) -> Any:
    return _get(f"/statistics/{int(match_id)}")


def get_last_five(team_id: int) -> Any:
    return _get("/last-five-games", {"teamId": int(team_id)})


def get_head_to_head(home_team_id: int, away_team_id: int) -> Any:
    return _get("/head-2-head", {"teamIdOne": int(home_team_id), "teamIdTwo": int(away_team_id)})


def get_team_statistics(team_id: int, from_date: str) -> Any:
    return _get(f"/teams/statistics/{int(team_id)}", {"fromDate": from_date})


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
