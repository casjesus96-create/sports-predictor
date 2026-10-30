"""Read-only audit of NFL schedule fields and advanced-stat source availability.

This module deliberately does not feed the official NFL-1.0.0 model.
"""
from datetime import datetime, timezone

import requests

from nfl_client import load_schedule


NFLVERSE_RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"
SOURCE_TIMEOUT_SECONDS = 6

FIELD_LABELS = {
    "away_qb": "Quarterback visitante",
    "home_qb": "Quarterback local",
    "temp": "Temperatura",
    "wind": "Viento",
    "roof": "Tipo de techo",
    "surface": "Superficie",
    "spread_line": "Línea de hándicap",
    "total_line": "Línea total de puntos",
}

ADVANCED_SOURCES = (
    {
        "key": "weekly_team_stats",
        "label": "Estadísticas semanales por equipo",
        "tag": "stats_team",
        "asset_template": "stats_team_week_{season}.csv.gz",
        "recommended_use": "EPA, eficiencia y producción de equipo por semana; verificar columnas y fecha antes de usar.",
    },
    {
        "key": "play_by_play",
        "label": "Jugadas históricas (play-by-play)",
        "tag": "pbp",
        "asset_template": "play_by_play_{season}.csv.gz",
        "recommended_use": "Construir métricas por partido: EPA/jugada, éxito, pase/carrera y tercera oportunidad.",
    },
    {
        "key": "weekly_rosters",
        "label": "Plantillas semanales",
        "tag": "weekly_rosters",
        "asset_template": "roster_weekly_{season}.csv.gz",
        "recommended_use": "Contexto de disponibilidad/plantilla; no equivale a un parte oficial de lesiones.",
    },
    {
        "key": "player_stats",
        "label": "Estadísticas de jugadores",
        "tag": "player_stats",
        "asset_template": "player_stats.csv.gz",
        "recommended_use": "Evaluar producción individual y quarterbacks; filtrar estrictamente por fecha/semana.",
    },
)


def _present(value):
    return value is not None and value != ""


def _probe_source(source, season, session=requests):
    asset = source["asset_template"].format(season=season)
    url = f"{NFLVERSE_RELEASES}/{source['tag']}/{asset}"
    try:
        response = session.head(
            url,
            allow_redirects=True,
            timeout=SOURCE_TIMEOUT_SECONDS,
        )
        available = 200 <= response.status_code < 400
        length = response.headers.get("Content-Length")
        try:
            size_bytes = int(length) if length else None
        except (TypeError, ValueError):
            size_bytes = None

        return {
            "key": source["key"],
            "label": source["label"],
            "available": available,
            "http_status": response.status_code,
            "asset": asset,
            "url": url if available else None,
            "size_bytes": size_bytes,
            "recommended_use": source["recommended_use"],
            "error": None if available else "La fuente no confirmó disponibilidad.",
        }
    except requests.RequestException as exc:
        return {
            "key": source["key"],
            "label": source["label"],
            "available": False,
            "http_status": None,
            "asset": asset,
            "url": None,
            "size_bytes": None,
            "recommended_use": source["recommended_use"],
            "error": f"Fuente temporalmente no verificable: {type(exc).__name__}.",
        }


def audit_nfl_data_coverage(season=2026, include_source_probes=True, session=requests):
    """Summarize real schedule-field coverage and probe public nflverse assets."""
    games = load_schedule(season=season)
    total = len(games)
    field_coverage = []

    for field, label in FIELD_LABELS.items():
        present = sum(1 for game in games if _present(game.get(field)))
        field_coverage.append({
            "field": field,
            "label": label,
            "present": present,
            "total": total,
            "coverage_pct": round(100 * present / total, 2) if total else 0.0,
            "missing": total - present,
        })

    valid_kickoff = sum(1 for game in games if _present(game.get("kickoff")))
    completed_with_score = sum(
        1 for game in games
        if _present(game.get("kickoff"))
        and game.get("home_score") is not None
        and game.get("away_score") is not None
    )

    sources = []
    if include_source_probes:
        sources = [
            _probe_source(source, season, session=session)
            for source in ADVANCED_SOURCES
        ]

    available_sources = sum(1 for source in sources if source["available"])
    return {
        "success": True,
        "sport": "NFL",
        "season": int(season),
        "model_version": "NFL-1.0.0",
        "read_only": True,
        "model_impact": "none",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schedule": {
            "games_found": total,
            "valid_kickoff": valid_kickoff,
            "games_with_both_scores": completed_with_score,
            "fields": field_coverage,
        },
        "advanced_sources": {
            "checked": len(sources),
            "available": available_sources,
            "sources": sources,
        },
        "next_step": (
            "Inspect the available source schemas and calculate historical "
            "pregame coverage before integrating any advanced metric."
        ),
    }
