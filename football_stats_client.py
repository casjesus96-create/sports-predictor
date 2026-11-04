"""API-Football statistics lookup for verified completed football matches.

This module is deliberately read-only: it never changes the official prediction
model and only returns match statistics after the primary fixture provider
confirms a completed match with a numeric full-time score.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

import requests

logger = logging.getLogger(__name__)
BASE_URL = "https://v3.football.api-sports.io"
TIMEOUT_SECONDS = 15
CACHE_TTL_SECONDS = 6 * 60 * 60
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = Lock()

STAT_LABELS = {
    "corner kicks": "corners",
    "total shots": "shots_total",
    "shots on goal": "shots_on_target",
    "shots off goal": "shots_off_target",
    "blocked shots": "shots_blocked",
    "fouls": "fouls",
    "yellow cards": "yellow_cards",
    "red cards": "red_cards",
    "ball possession": "possession",
    "total passes": "passes_total",
    "passes accurate": "passes_accurate",
    "pass accuracy": "pass_accuracy",
    "offsides": "offsides",
    "goalkeeper saves": "goalkeeper_saves",
}


class APIFootballError(Exception):
    """Safe provider error with an HTTP-compatible status code."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _normalize_team(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    tokens = value.split()
    while tokens and tokens[-1] in {"fc", "cf", "afc", "sc", "club"}:
        tokens.pop()
    return " ".join(tokens)

def _cache_get(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at <= monotonic():
            _cache.pop(key, None)
            return None
        return value


def _cache_set(key: str, value: dict):
    with _cache_lock:
        _cache[key] = (monotonic() + CACHE_TTL_SECONDS, value)


def clear_cache():
    with _cache_lock:
        _cache.clear()


def _request(endpoint: str, params: dict) -> dict:
    api_key = os.getenv("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        raise APIFootballError(
            "API-Football no está configurado. Añade API_FOOTBALL_KEY en Render.",
            503,
        )
    base_url = os.getenv("API_FOOTBALL_BASE_URL", BASE_URL).rstrip("/")
    try:
        response = requests.get(
            f"{base_url}/{endpoint.lstrip('/')}",
            headers={"x-apisports-key": api_key},
            params=params,
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code == 429:
            raise APIFootballError("API-Football alcanzó el límite de consultas.", 429)
        if response.status_code in (401, 403):
            raise APIFootballError("API-Football rechazó la clave o el plan configurado.", 503)
        response.raise_for_status()
        payload = response.json()
    except APIFootballError:
        raise
    except requests.RequestException as exc:
        logger.warning("API-Football request failed: %s", exc)
        raise APIFootballError("No fue posible consultar API-Football.", 502) from exc
    except (ValueError, TypeError) as exc:
        raise APIFootballError("API-Football devolvió una respuesta inválida.", 502) from exc

    errors = payload.get("errors")
    if errors:
        logger.warning("API-Football returned provider errors: %s", errors)
        raise APIFootballError("API-Football no pudo completar la consulta.", 502)
    return payload


def _numeric(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return None


def get_completed_match_statistics(
    match_id: int,
    home_team: str,
    away_team: str,
    kickoff_at: str,
) -> dict:
    """Resolve a fixture by exact team names/date, then return its final stats."""
    if not isinstance(match_id, int) or isinstance(match_id, bool) or match_id <= 0:
        raise APIFootballError("Identificador de partido inválido.", 400)
    try:
        kickoff = datetime.fromisoformat(str(kickoff_at).replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            raise ValueError("timezone required")
    except (TypeError, ValueError) as exc:
        raise APIFootballError("La fecha del partido no es válida.", 400) from exc
    if kickoff > datetime.now(timezone.utc):
        raise APIFootballError("Las estadísticas solo están disponibles para partidos ya finalizados.", 409)

    home_key, away_key = _normalize_team(home_team), _normalize_team(away_team)
    if not home_key or not away_key:
        raise APIFootballError("No se pudieron identificar ambos equipos.", 400)

    date_key = kickoff.astimezone(timezone.utc).date().isoformat()
    fixture_cache_key = f"fixtures:{date_key}"
    fixtures_payload = _cache_get(fixture_cache_key)
    if fixtures_payload is None:
        fixtures_payload = _request("fixtures", {"date": date_key})
        _cache_set(fixture_cache_key, fixtures_payload)

    candidates = []
    for item in fixtures_payload.get("response", []):
        teams = item.get("teams") or {}
        candidate_home = _normalize_team((teams.get("home") or {}).get("name", ""))
        candidate_away = _normalize_team((teams.get("away") or {}).get("name", ""))
        if candidate_home == home_key and candidate_away == away_key:
            candidates.append(item)

    if len(candidates) != 1:
        raise APIFootballError(
            "No se encontró una coincidencia única de equipos y fecha en API-Football.",
            404,
        )

    fixture = candidates[0]
    fixture_info = fixture.get("fixture") or {}
    fixture_id = fixture_info.get("id")
    fixture_status = str((fixture_info.get("status") or {}).get("short") or "").upper()
    if fixture_status not in {"FT", "AET", "PEN"}:
        raise APIFootballError("API-Football todavía no confirma el partido como finalizado.", 409)
    if not isinstance(fixture_id, int) or fixture_id <= 0:
        raise APIFootballError("API-Football no devolvió un identificador válido del encuentro.", 502)

    stats_cache_key = f"statistics:{fixture_id}"
    stats_payload = _cache_get(stats_cache_key)
    if stats_payload is None:
        stats_payload = _request("fixtures/statistics", {"fixture": fixture_id})
        _cache_set(stats_cache_key, stats_payload)

    rows = stats_payload.get("response") or []
    by_team = {}
    for row in rows:
        team_name = (row.get("team") or {}).get("name")
        team_key = _normalize_team(team_name)
        values = {}
        for stat in row.get("statistics") or []:
            label = str(stat.get("type") or "").strip().lower()
            field = STAT_LABELS.get(label)
            if field:
                values[field] = _numeric(stat.get("value"))
        if team_key:
            by_team[team_key] = values

    if home_key not in by_team or away_key not in by_team:
        raise APIFootballError("API-Football no devolvió estadísticas completas para ambos equipos.", 404)

    return {
        "available": True,
        "provider": "API-Football",
        "provider_fixture_id": fixture_id,
        "source_match_id": match_id,
        "match_status": fixture_status,
        "date": fixture_info.get("date"),
        "home_team": {"name": home_team, "statistics": by_team[home_key]},
        "away_team": {"name": away_team, "statistics": by_team[away_key]},
        "data_scope": "Estadísticas observadas de un encuentro finalizado; no son probabilidades.",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
