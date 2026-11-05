"""Highlightly direct Football API client with bounded cache and sanitized errors."""
from __future__ import annotations

import logging
import os
import time
import unicodedata
from datetime import datetime, timezone
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
_rate_limit_until = 0.0
_rate_limit_message = "Highlightly ha limitado temporalmente las solicitudes."
_request_locks: dict[tuple, Lock] = {}
_provider_status: dict[str, Any] = {}
_quota_state_loaded = False
logger = logging.getLogger(__name__)


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


def _header_int(headers: Any, *names: str) -> int | None:
    for name in names:
        value = headers.get(name)
        if value is None:
            continue
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            continue
    return None


def _reset_seconds(headers: Any) -> int | None:
    value = _header_int(
        headers,
        "x-ratelimit-requests-reset",
        "X-RateLimit-Requests-Reset",
        "ratelimit-reset",
        "RateLimit-Reset",
    )
    if value is None:
        return None
    # RapidAPI commonly reports a duration; some gateways report a Unix epoch.
    seconds = value - int(time.time()) if value > 86400 else value
    return max(1, min(seconds, 86400)) if seconds > 0 else None


def _quota_store_client():
    """Get the existing Supabase service client lazily to avoid import cycles."""
    from repository import get_supabase_client
    return get_supabase_client()


def _load_persisted_quota_state() -> None:
    """Restore a provider cooldown after a Render process restart."""
    global _quota_state_loaded, _rate_limit_until, _rate_limit_message
    with _cache_lock:
        if _quota_state_loaded:
            return
        _quota_state_loaded = True
    try:
        response = (
            _quota_store_client()
            .table("provider_quota_state")
            .select("state")
            .eq("provider", "Highlightly")
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows or not isinstance(rows[0].get("state"), dict):
            return
        state = dict(rows[0]["state"])
        blocked_until = int(state.get("blocked_until_epoch") or 0)
        wait = max(0, blocked_until - int(time.time()))
        with _cache_lock:
            _provider_status.update({k: v for k, v in state.items() if k != "blocked_until_epoch"})
            if wait:
                _rate_limit_until = time.monotonic() + wait
                _rate_limit_message = str(state.get("message") or "Highlightly ha limitado las solicitudes.")
    except Exception as exc:
        # Provider access must remain available even if optional quota persistence is unavailable.
        logger.warning("No se pudo restaurar el estado de cuota Highlightly desde Supabase: %s", exc)


def _persist_quota_state(blocked_until_epoch: int = 0) -> None:
    """Persist sanitized quota diagnostics; never store API credentials or response bodies."""
    with _cache_lock:
        state = dict(_provider_status)
    state["blocked_until_epoch"] = int(blocked_until_epoch)
    try:
        _quota_store_client().table("provider_quota_state").upsert({
            "provider": "Highlightly",
            "state": state,
            "updated_at": datetime.fromtimestamp(time.time(), timezone.utc).isoformat(),
        }, on_conflict="provider").execute()
    except Exception as exc:
        logger.warning("No se pudo persistir el estado de cuota Highlightly en Supabase: %s", exc)


def get_provider_status() -> dict[str, Any]:
    """Return last observed provider/quota diagnostics without making an API request."""
    _load_persisted_quota_state()
    with _cache_lock:
        status = dict(_provider_status)
        wait = max(0, int(_rate_limit_until - time.monotonic()))
    status["cooldown_active"] = wait > 0
    status["retry_after_seconds"] = wait
    status.setdefault("provider", "Highlightly")
    status.setdefault("state", "unknown")
    return status


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    token = _key()
    _load_persisted_quota_state()
    clean = tuple(sorted((str(k), str(v)) for k, v in (params or {}).items() if v is not None))
    cache_key = (path, clean)
    now = time.monotonic()
    global _rate_limit_until, _rate_limit_message
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
        request_lock = _request_locks.setdefault(cache_key, Lock())

    try:
        # Coalesce simultaneous identical cache misses into one provider request.
        with request_lock:
            now = time.monotonic()
            with _cache_lock:
                cached = _cache.get(cache_key)
                if cached and cached[0] > now:
                    return cached[1]
                if _rate_limit_until > now:
                    wait_seconds = max(1, int(_rate_limit_until - now))
                    raise HighlightlyError(
                        f"{_rate_limit_message} Reintento bloqueado temporalmente; espera aproximadamente {wait_seconds} segundos.",
                        429,
                    )
            try:
                response = requests.get(
                    f"{BASE_URL}{path}",
                    headers={"x-rapidapi-key": token, "Accept": "application/json"},
                    params=dict(clean),
                    timeout=TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                with _cache_lock:
                    _provider_status.update({
                        "provider": "Highlightly", "state": "connection_error",
                        "last_http_status": None, "message": "No fue posible conectar con Highlightly.",
                        "observed_at": int(time.time()),
                    })
                raise HighlightlyError("No fue posible conectar con Highlightly.") from exc

            headers = response.headers
            remaining = _header_int(headers, "x-ratelimit-requests-remaining", "X-RateLimit-Requests-Remaining")
            limit = _header_int(headers, "x-ratelimit-requests-limit", "X-RateLimit-Requests-Limit")
            reset_seconds = _reset_seconds(headers)
            if response.status_code == 429:
                retry_after = _header_int(headers, "Retry-After", "retry-after")
                try:
                    error_payload = response.json()
                    provider_error_text = str(error_payload).casefold()
                except (ValueError, AttributeError):
                    provider_error_text = ""
                daily_quota_signal = any(
                    marker in provider_error_text
                    for marker in ("daily quota", "daily limit", "quota exceeded", "daily request")
                )
                exhausted = remaining == 0 or daily_quota_signal
                cooldown_seconds = retry_after or reset_seconds or (3600 if exhausted else 60)
                cooldown_seconds = max(30, min(cooldown_seconds, 86400))
                message = (
                    "Highlightly indica que se agotó la cuota disponible."
                    if exhausted else
                    "Highlightly aplicó un límite temporal de solicitudes."
                )
                blocked_until_epoch = int(time.time()) + cooldown_seconds
                with _cache_lock:
                    _rate_limit_until = time.monotonic() + cooldown_seconds
                    _rate_limit_message = message
                    _provider_status.update({
                        "provider": "Highlightly", "state": "quota_exhausted" if exhausted else "rate_limited",
                        "last_http_status": 429, "message": message,
                        "quota_remaining": remaining, "quota_limit": limit,
                        "quota_reset_seconds": reset_seconds,
                        "retry_after_header_seconds": retry_after,
                        "cooldown_source": "Retry-After" if retry_after else ("rate-limit-reset" if reset_seconds else "fallback"),
                        "observed_at": int(time.time()),
                    })
                _persist_quota_state(blocked_until_epoch)
                raise HighlightlyError(
                    f"{message} Se pausaron nuevas consultas durante aproximadamente {cooldown_seconds} segundos.",
                    429,
                )
            if response.status_code == 401:
                raise HighlightlyError("Highlightly rechazó la clave configurada (HTTP 401). Revisa HIGHLIGHTLY_API_KEY en Render.", 502)
            if response.status_code == 403:
                raise HighlightlyError("Highlightly rechazó la solicitud o el acceso al recurso (HTTP 403).", 502)
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
                _provider_status.update({
                    "provider": "Highlightly", "state": "available",
                    "last_http_status": response.status_code, "message": "Última consulta correcta.",
                    "quota_remaining": remaining, "quota_limit": limit,
                    "quota_reset_seconds": reset_seconds,
                    "observed_at": int(time.time()),
                })
            _persist_quota_state(0)
            return data
    finally:
        with _cache_lock:
            if _request_locks.get(cache_key) is request_lock:
                _request_locks.pop(cache_key, None)


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    tokens = "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
    ignored = {"fc", "cf", "afc", "sc", "ac", "ec", "cd", "ud", "sd", "fk", "sk", "de", "the"}
    return " ".join(token for token in tokens if token not in ignored)


TEAM_NAME_ALIAS_GROUPS = (
    {"coventry", "coventry city"},
    {"leeds", "leeds united"},
    {"tottenham", "tottenham hotspur"},
    {"racing santander", "real racing club santander"},
    {"espanyol", "rcd espanyol barcelona"},
    {"deportivo la coruna", "rc deportivo la coruna"},
)


def _team_names_match(first: str, second: str) -> bool:
    first_normalized = normalize_name(first)
    second_normalized = normalize_name(second)
    if first_normalized == second_normalized:
        return True
    return any(
        first_normalized in aliases and second_normalized in aliases
        for aliases in TEAM_NAME_ALIAS_GROUPS
    )


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
            # The primary provider labels Spain's top men's division as
            # "Primera Division"; Highlightly catalogs it as "La Liga".
            # Country-code filtering below prevents collisions with other
            # countries and excludes Spain's women's/second divisions.
            "primera division": {"la liga"},
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
        highlightly_home = str(home_data.get("name", ""))
        highlightly_away = str(away_data.get("name", ""))
        kickoff = str(row.get("date") or "")
        league = row.get("league") or {}
        league_matches = expected_league_id is None or league.get("id") == expected_league_id
        if (
            _team_names_match(home_name, highlightly_home)
            and _team_names_match(away_name, highlightly_away)
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


def get_leagues(page_size: int = 100, max_pages: int = 20) -> list[dict[str, Any]]:
    """Return Highlightly's own paginated league catalog, preserving provider IDs/names."""
    safe_page_size = max(1, min(int(page_size), 100))
    safe_max_pages = max(1, min(int(max_pages), 20))
    leagues: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for page_number in range(safe_max_pages):
        offset = page_number * safe_page_size
        payload = _get("/leagues", {"limit": safe_page_size, "offset": offset})
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise HighlightlyError("Highlightly devolvió un catálogo de competiciones con formato inesperado.")
        for row in rows:
            if not isinstance(row, dict):
                continue
            league_id = row.get("id")
            if isinstance(league_id, int) and not isinstance(league_id, bool) and league_id > 0 and league_id not in seen_ids:
                leagues.append(row)
                seen_ids.add(league_id)
        pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
        total_count = pagination.get("totalCount")
        if not rows or len(rows) < safe_page_size:
            break
        if isinstance(total_count, int) and offset + len(rows) >= total_count:
            break
    return leagues


def get_league_matches(league_id: int, match_date: str, page_size: int = 100) -> list[dict[str, Any]]:
    """Return fixtures for a Highlightly league ID and date; no team-name resolution."""
    if isinstance(league_id, bool) or not isinstance(league_id, int) or league_id <= 0:
        raise HighlightlyError("Identificador de competición Highlightly inválido.", 400)
    try:
        from datetime import date as _date
        _date.fromisoformat(str(match_date))
    except (TypeError, ValueError) as exc:
        raise HighlightlyError("La fecha solicitada no es válida (YYYY-MM-DD).", 400) from exc
    safe_page_size = max(1, min(int(page_size), 100))
    rows_out: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for page_number in range(10):
        offset = page_number * safe_page_size
        payload = _get("/matches", {"leagueId": league_id, "date": match_date, "limit": safe_page_size, "offset": offset})
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise HighlightlyError("Highlightly devolvió un calendario con formato inesperado.")
        for row in rows:
            if not isinstance(row, dict):
                continue
            match_id = row.get("id")
            league = row.get("league") or {}
            if league.get("id") == league_id and isinstance(match_id, int) and not isinstance(match_id, bool) and match_id not in seen_ids and str(row.get("date") or "")[:10] == match_date:
                rows_out.append(row)
                seen_ids.add(match_id)
        pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
        total_count = pagination.get("totalCount")
        if not rows or len(rows) < safe_page_size:
            break
        if isinstance(total_count, int) and offset + len(rows) >= total_count:
            break
    return rows_out


def get_fixture(match_id: int) -> dict[str, Any]:
    """Fetch a Highlightly fixture by its own ID."""
    if isinstance(match_id, bool) or not isinstance(match_id, int) or match_id <= 0:
        raise HighlightlyError("Identificador de partido Highlightly inválido.", 400)
    payload = _get(f"/matches/{match_id}")
    if isinstance(payload, dict):
        candidate = payload.get("match") or payload.get("data") or payload
        if isinstance(candidate, dict) and candidate.get("id") == match_id:
            return candidate
    raise HighlightlyError("Highlightly no devolvió el encuentro solicitado.", 404)


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
