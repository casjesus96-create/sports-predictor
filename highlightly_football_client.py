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
    "/countries": 86400,
    "/leagues": 86400,
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


def _resolve_country_code(country_name: str) -> str:
    """Resolve a Highlightly ISO country code from its canonical country list."""
    payload = _get("/countries", {"name": str(country_name).strip()})
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise HighlightlyError("Highlightly devolvió un formato inesperado al consultar los países.")
    expected_country = normalize_name(country_name)
    exact = [
        row for row in rows
        if isinstance(row, dict)
        and normalize_name(row.get("name", "")) == expected_country
        and isinstance(row.get("code"), str)
        and row.get("code").strip()
    ]
    if len(exact) != 1:
        candidates = [str(row.get("name", "?")) for row in rows if isinstance(row, dict)][:6]
        detail = f" Países devueltos: {'; '.join(candidates)}." if candidates else ""
        raise HighlightlyError(
            f"No se pudo resolver un código de país único en Highlightly para '{country_name}'.{detail}",
            404 if not exact else 409,
        )
    return exact[0]["code"].strip().upper()


def _resolve_league_id(league_name: str, country_name: str | None = None) -> int:
    """Resolve a league by exact normalized name and Highlightly ISO country code."""
    params: dict[str, Any] = {"leagueName": str(league_name).strip(), "limit": 100, "offset": 0}
    expected_country = normalize_name(country_name) if country_name else ""
    country_code = _resolve_country_code(country_name) if expected_country else None
    if country_code:
        params["countryCode"] = country_code
    payload = _get("/leagues", params)
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise HighlightlyError("Highlightly devolvió un formato inesperado al consultar las competiciones.")

    expected_name = normalize_name(league_name)
    exact = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), int):
            continue
        if normalize_name(row.get("name", "")) != expected_name:
            continue
        country = row.get("country") or {}
        if expected_country and normalize_name(country.get("name", "")) != expected_country:
            continue
        if country_code and str(country.get("code", "")).strip().upper() != country_code:
            continue
        exact.append(row)

    # Highlightly may index a competition under a shorter/localized name
    # (for example "Serie A") even when the primary provider calls it
    # "Campeonato Brasileiro Série A". If the exact-name query returned no
    # match, inspect the country catalog and resolve only a known alias.
    if not exact and country_code:
        aliases_by_source_name = {
            "campeonato brasileiro serie a": {
                "campeonato brasileiro serie a",
                "brasileirao serie a",
                "brasileiro serie a",
                "serie a",
            },
        }
        aliases = aliases_by_source_name.get(expected_name, {expected_name})
        catalog_rows = []
        offset = 0
        while offset < 1000:
            catalog_payload = _get(
                "/leagues",
                {"countryCode": country_code, "limit": 100, "offset": offset},
            )
            page = catalog_payload.get("data", []) if isinstance(catalog_payload, dict) else catalog_payload
            if not isinstance(page, list) or not page:
                break
            catalog_rows.extend(row for row in page if isinstance(row, dict))
            pagination = catalog_payload.get("pagination", {}) if isinstance(catalog_payload, dict) else {}
            total_count = pagination.get("totalCount")
            offset += len(page)
            if not isinstance(total_count, int) or offset >= total_count or len(page) < 100:
                break
        exact = [
            row for row in catalog_rows
            if isinstance(row.get("id"), int)
            and normalize_name(row.get("name", "")) in aliases
            and str((row.get("country") or {}).get("code", "")).strip().upper() == country_code
        ]
        rows = catalog_rows

    if len(exact) != 1:
        candidates = [
            f"{row.get('name', '?')} ({(row.get('country') or {}).get('name', 'país no indicado')})"
            for row in rows if isinstance(row, dict)
        ][:8]
        detail = f" Opciones devueltas: {'; '.join(candidates)}." if candidates else ""
        country_detail = f" País solicitado: '{country_name}'." if country_name else ""
        raise HighlightlyError(
            f"No se pudo identificar una competición única en Highlightly para '{league_name}'."
            f"{country_detail}{detail}",
            404 if not exact else 409,
        )
    return exact[0]["id"]



def find_fixture(
    date: str,
    home_name: str,
    away_name: str,
    league_name: str | None = None,
    country_name: str | None = None,
) -> dict:
    """Resolve a fixture by date and verified teams; scope the provider query by league ID."""
    expected_home = normalize_name(home_name)
    expected_away = normalize_name(away_name)
    if not expected_home or not expected_away:
        raise HighlightlyError("No se pudieron normalizar los nombres de los equipos.", 422)

    params: dict[str, Any] = {"date": date, "limit": 100, "offset": 0}
    expected_league_id = None
    if league_name and str(league_name).strip():
        expected_league_id = _resolve_league_id(league_name, country_name)
        params["leagueId"] = expected_league_id

    payload = _get("/matches", params)
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise HighlightlyError("Highlightly devolvió un formato inesperado al buscar el partido.")

    matches = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        home_data = row.get("homeTeam") or {}
        away_data = row.get("awayTeam") or {}
        home = normalize_name(home_data.get("name", ""))
        away = normalize_name(away_data.get("name", ""))
        kickoff = str(row.get("date") or "")
        league = row.get("league") or {}
        league_matches = expected_league_id is None or league.get("id") == expected_league_id
        if (
            home == expected_home
            and away == expected_away
            and kickoff[:10] == date
            and league_matches
            and isinstance(row.get("id"), int)
        ):
            matches.append(row)

    if len(matches) != 1:
        if not matches:
            same_day = [
                f"{(row.get('homeTeam') or {}).get('name', '?')} vs "
                f"{(row.get('awayTeam') or {}).get('name', '?')} "
                f"[{((row.get('league') or {}).get('name') or 'competición no indicada')}]"
                for row in rows if isinstance(row, dict)
            ][:8]
            if same_day:
                raise HighlightlyError(
                    "Highlightly devolvió partidos para la fecha, pero no encontró una "
                    "coincidencia exacta de equipos, fecha y competición. "
                    f"Partidos recibidos: {'; '.join(same_day)}",
                    404,
                )
            raise HighlightlyError("Highlightly no devolvió partidos para la fecha y competición solicitadas.", 404)
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
