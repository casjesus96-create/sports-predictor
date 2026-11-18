"""Historical ATP/WTA match-statistics adapter.

This module is a data foundation, not a prediction model. It reads the
Jeff Sackmann annual match CSVs on demand, filters every match to dates
strictly before the requested cutoff, and calculates transparent player
profiles. It does not infer missing stats or produce win probabilities.

Source datasets have their own licensing terms. Review them before any
commercial use; the endpoint reports the upstream source for traceability.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import requests

from tennis_archive import get_player_archive_profile

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 20
MAX_PROFILE_LOOKBACK_DAYS = 730
SOURCE_FRESHNESS_CURRENT_MAX_DAYS = 45
SOURCE_FRESHNESS_DELAYED_MAX_DAYS = 90
SUPPORTED_LEAGUES = {"ATP", "WTA"}
# The original Jeff Sackmann repositories are no longer reliably available.
# This archival mirror preserves the original CSV schema and includes seasons
# through 2026. The underlying dataset remains CC BY-NC-SA 4.0.
BASE_URLS = {
    "ATP": "https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main/atp",
    "WTA": "https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main/wta",
}
SOURCE_REPOSITORY_URLS = {
    "ATP": "https://github.com/Aneeshers/tennis-sackmann-archive/tree/main/atp",
    "WTA": "https://github.com/Aneeshers/tennis-sackmann-archive/tree/main/wta",
}
UPSTREAM_PROVENANCE_URLS = {
    "ATP": "https://github.com/JeffSackmann/tennis_atp",
    "WTA": "https://github.com/JeffSackmann/tennis_wta",
}
HEADERS = {"User-Agent": "Sports-Predictor-Tennis-History/1.0", "Accept": "text/csv"}
STAT_FIELDS = {
    "winner": ("w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_bpSaved", "w_bpFaced"),
    "loser": ("l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_bpSaved", "l_bpFaced"),
}


class HistoricalDataError(RuntimeError):
    """Raised when historical source data cannot be read safely."""


def parse_cutoff(value: str | date | datetime | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("cutoff_date debe usar formato YYYY-MM-DD.") from exc


def normalize_player_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_name = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_name.casefold()).strip()


def _integer(value: Any) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _ratio(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0 or numerator > denominator:
        return None
    return round(numerator / denominator, 4)


@lru_cache(maxsize=16)
def load_year(league: str, year: int) -> tuple[dict[str, str], ...]:
    """Load one annual CSV. Successful responses are cached in-process."""
    league = str(league).strip().upper()
    if league not in SUPPORTED_LEAGUES:
        raise ValueError("league debe ser ATP o WTA.")
    if year < 1968 or year > datetime.now(timezone.utc).year:
        raise ValueError("Año histórico fuera del rango permitido.")
    filename = "atp_matches" if league == "ATP" else "wta_matches"
    url = f"{BASE_URLS[league]}/{filename}_{year}.csv"
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        if response.status_code == 404:
            # Some annual files have not been published yet; missing year is
            # reported as unavailable rather than treated as an empty season.
            return ()
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        required = {"tourney_date", "winner_name", "loser_name", "surface"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise HistoricalDataError(f"El CSV histórico {year} no tiene las columnas esperadas.")
        return tuple(dict(row) for row in reader)
    except requests.RequestException as exc:
        logger.warning("No se pudo cargar histórico %s %s: %s", league, year, exc)
        raise HistoricalDataError(
            f"No se pudo consultar el histórico {league} {year}."
        ) from exc


def _match_date(row: dict[str, str]) -> date | None:
    raw = str(row.get("tourney_date") or "").strip()
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        return None


def _player_side(row: dict[str, str], player_key: str) -> str | None:
    name_key = normalize_player_name(row.get("winner_name", "")), normalize_player_name(row.get("loser_name", ""))
    target = normalize_player_name(player_key)
    if target and target == name_key[0]:
        return "winner"
    if target and target == name_key[1]:
        return "loser"
    return None


def _match_stats(row: dict[str, str], side: str) -> dict[str, int | None]:
    prefix = "w" if side == "winner" else "l"
    return {
        field: _integer(row.get(f"{prefix}_{field}"))
        for field in ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "bpSaved", "bpFaced")
    }


def _sum_available(values: list[int | None]) -> int | None:
    usable = [value for value in values if value is not None]
    return sum(usable) if usable else None


def _aggregate_service_stats(matches: list[tuple[dict[str, str], str]]) -> dict[str, Any]:
    # Only matches with a valid service-points denominator count as played
    # observations for service coverage and per-match averages.
    stats = [
        item for item in (_match_stats(row, side) for row, side in matches)
        if item["svpt"] is not None and item["svpt"] > 0
    ]
    aces = _sum_available([item["ace"] for item in stats])
    double_faults = _sum_available([item["df"] for item in stats])
    serve_points = _sum_available([item["svpt"] for item in stats])
    first_in = _sum_available([item["1stIn"] for item in stats])
    first_won = _sum_available([item["1stWon"] for item in stats])
    second_won = _sum_available([item["2ndWon"] for item in stats])
    bp_saved = _sum_available([item["bpSaved"] for item in stats])
    bp_faced = _sum_available([item["bpFaced"] for item in stats])
    second_attempts = (
        sum(item["svpt"] - item["1stIn"] for item in stats if item["svpt"] is not None and item["1stIn"] is not None)
        if any(item["svpt"] is not None and item["1stIn"] is not None for item in stats)
        else None
    )
    return {
        "matches_with_service_stats": len(stats),
        "aces_total": aces,
        "double_faults_total": double_faults,
        "aces_per_match": round(aces / len(stats), 3) if aces is not None and stats else None,
        "double_faults_per_match": round(double_faults / len(stats), 3) if double_faults is not None and stats else None,
        "first_serve_in_pct": _ratio(first_in, serve_points),
        "first_serve_points_won_pct": _ratio(first_won, first_in),
        "second_serve_points_won_pct": _ratio(second_won, second_attempts),
        "break_points_saved_pct": _ratio(bp_saved, bp_faced),
    }


def get_player_profile(
    player_name: str,
    league: str = "ATP",
    cutoff_date: str | date | datetime | None = None,
    surface: str | None = None,
    lookback_days: int = 365,
) -> dict[str, Any]:
    """Build a transparent, pre-match profile from annual historical CSVs."""
    league = str(league or "").strip().upper()
    if league not in SUPPORTED_LEAGUES:
        raise ValueError("league debe ser ATP o WTA.")
    player_name = str(player_name or "").strip()
    if not player_name or len(player_name) > 120:
        raise ValueError("player_name es obligatorio y debe tener máximo 120 caracteres.")
    if not 30 <= int(lookback_days) <= MAX_PROFILE_LOOKBACK_DAYS:
        raise ValueError("lookback_days debe estar entre 30 y 730.")
    cutoff = parse_cutoff(cutoff_date)
    selected_surface = str(surface or "").strip().title() or None
    if selected_surface and selected_surface not in {"Hard", "Clay", "Grass", "Carpet"}:
        raise ValueError("surface debe ser Hard, Clay, Grass o Carpet.")

    # Prefer the persistent CC BY 4.0 archive for recent form, while retaining
    # the legacy source as a separate provider of serve statistics/rankings.
    archived_profile = None
    try:
        archived_profile = get_player_archive_profile(
            player_name=player_name,
            league=league,
            cutoff_date=cutoff,
            lookback_days=int(lookback_days),
            surface=selected_surface,
        )
        if archived_profile and archived_profile.get("identity_ambiguous"):
            archived_profile = None
    except Exception as exc:
        logger.warning("Persistent tennis archive unavailable; using legacy source: %s", exc)

    # Include enough recent seasons to cover the lookback window. The profile
    # uses event dates strictly earlier than cutoff to prevent target leakage.
    first_year = (cutoff - timedelta(days=int(lookback_days))).year
    rows: list[tuple[date, dict[str, str]]] = []
    years_available: list[int] = []
    source_dates: list[date] = []
    try:
        for year in range(first_year, cutoff.year + 1):
            annual_rows = load_year(league, year)
            if annual_rows:
                years_available.append(year)
            for row in annual_rows:
                played_on = _match_date(row)
                if played_on and played_on < cutoff:
                    source_dates.append(played_on)
                if played_on and cutoff - timedelta(days=int(lookback_days)) <= played_on < cutoff:
                    rows.append((played_on, row))
    except Exception as exc:
        if archived_profile:
            logger.warning("Legacy tennis serve-stat source unavailable; retaining current archive profile: %s", exc)
            return archived_profile
        raise
    rows.sort(key=lambda item: (item[0], str(item[1].get("tourney_id") or ""), str(item[1].get("match_num") or "")))
    latest_source_match_date = max(source_dates) if source_dates else None
    source_data_age_days = (cutoff - latest_source_match_date).days if latest_source_match_date else None
    source_freshness_status = (
        "unknown" if source_data_age_days is None
        else "current" if source_data_age_days <= SOURCE_FRESHNESS_CURRENT_MAX_DAYS
        else "delayed" if source_data_age_days <= SOURCE_FRESHNESS_DELAYED_MAX_DAYS
        else "stale"
    )

    target = normalize_player_name(player_name)
    matching_names = set()
    player_matches: list[tuple[date, dict[str, str], str]] = []
    for played_on, row in rows:
        winner_name = row.get("winner_name") or ""
        loser_name = row.get("loser_name") or ""
        winner_match = normalize_player_name(winner_name) == target
        loser_match = normalize_player_name(loser_name) == target
        if winner_match:
            matching_names.add(winner_name)
            player_matches.append((played_on, row, "winner"))
        elif loser_match:
            matching_names.add(loser_name)
            player_matches.append((played_on, row, "loser"))

    if len(matching_names) > 1:
        raise ValueError("El nombre coincide con más de una variante histórica; se necesita identificar al jugador con mayor precisión.")

    filtered = [
        entry for entry in player_matches
        if not selected_surface or str(entry[1].get("surface") or "").title() == selected_surface
    ]
    last_5 = player_matches[-5:]
    last_10 = player_matches[-10:]
    last_played = player_matches[-1][0] if player_matches else None
    last_7_start = cutoff - timedelta(days=7)
    last_14_start = cutoff - timedelta(days=14)
    matches_7 = [entry for entry in player_matches if entry[0] >= last_7_start]
    matches_14 = [entry for entry in player_matches if entry[0] >= last_14_start]
    stat_rows = [(row, side) for _, row, side in player_matches]
    wins = sum(side == "winner" for _, _, side in player_matches)
    surface_wins = sum(side == "winner" for _, _, side in filtered)
    recent_service = [(row, side) for _, row, side in player_matches[-10:]]
    recent_matches = []
    for played_on, row, side in reversed(player_matches[-10:]):
        opponent = row.get("loser_name") if side == "winner" else row.get("winner_name")
        recent_matches.append({
            "date": played_on.isoformat(),
            "date_precision": "tournament_start_date",
            "is_walkover": bool(re.search(r"\bW\s*/?\s*O\b|\bWALKOVER\b", str(row.get("score") or ""), re.IGNORECASE)),
            "tournament": row.get("tourney_name") or None,
            "opponent": str(opponent or "Desconocido"),
            "result": "W" if side == "winner" else "L",
            "score": str(row.get("score") or "").strip() or None,
            "surface": str(row.get("surface") or "").strip() or None,
            "round": str(row.get("round") or "").strip() or None,
        })
    rankings = []
    for _, row, side in player_matches:
        rank = _integer(row.get("winner_rank" if side == "winner" else "loser_rank"))
        if rank:
            rankings.append(rank)

    legacy_profile = {
        "success": True,
        "league": league,
        "player_name": next(iter(matching_names), player_name),
        "cutoff_date_exclusive": cutoff.isoformat(),
        "lookback_days": int(lookback_days),
        "surface_filter": selected_surface,
        "matches_in_window": len(player_matches),
        "wins_in_window": wins,
        "losses_in_window": len(player_matches) - wins,
        "win_rate": round(wins / len(player_matches), 4) if player_matches else None,
        "last_5": {
            "matches": len(last_5),
            "wins": sum(side == "winner" for _, _, side in last_5),
            "losses": sum(side == "loser" for _, _, side in last_5),
            "win_rate": round(sum(side == "winner" for _, _, side in last_5) / len(last_5), 4) if last_5 else None,
        },
        "last_10": {
            "matches": len(last_10),
            "wins": sum(side == "winner" for _, _, side in last_10),
            "losses": sum(side == "loser" for _, _, side in last_10),
            "win_rate": round(sum(side == "winner" for _, _, side in last_10) / len(last_10), 4) if last_10 else None,
        },
        "recent_matches": recent_matches,
        "surface_window": {
            "matches": len(filtered),
            "wins": surface_wins,
            "losses": len(filtered) - surface_wins,
            "win_rate": round(surface_wins / len(filtered), 4) if filtered else None,
        },
        "ranking_latest_in_window": rankings[-1] if rankings else None,
        "days_since_last_match": (cutoff - last_played).days if last_played else None,
        "workload_matches_last_7_days": len(matches_7),
        "workload_matches_last_14_days": len(matches_14),
        "service_return_stats_last_10_matches": _aggregate_service_stats(recent_service),
        "data_quality": {
            "annual_files_available": years_available,
            "matches_found": len(player_matches),
            "matches_with_service_stats": _aggregate_service_stats(recent_service)["matches_with_service_stats"],
            "latest_match_date_in_source": latest_source_match_date.isoformat() if latest_source_match_date else None,
            "source_data_age_days": source_data_age_days,
            "source_freshness_status": source_freshness_status,
            "source_freshness_thresholds_days": {
                "current_max": SOURCE_FRESHNESS_CURRENT_MAX_DAYS,
                "delayed_max": SOURCE_FRESHNESS_DELAYED_MAX_DAYS,
            },
            "source": f"Jeff Sackmann {league} historical match CSVs",
            "source_url": SOURCE_REPOSITORY_URLS[league],
            "upstream_provenance_url": UPSTREAM_PROVENANCE_URLS[league],
            "warning": (
                "Las estadísticas de servicio no están disponibles para todos los partidos. "
                "El perfil solo cubre los archivos anuales accesibles y el periodo solicitado."
                + (f" El último resultado presente en los archivos consultados es del {latest_source_match_date.isoformat()} "
                   f"({source_data_age_days} días antes del corte); la cobertura histórica está desactualizada."
                   if source_freshness_status == "stale" else "")
            ),
        },
    }

    if archived_profile:
        archive_quality = dict(archived_profile.get("data_quality") or {})
        legacy_quality = legacy_profile.get("data_quality") or {}
        legacy_service = legacy_profile.get("service_return_stats_last_10_matches") or {}
        archive_quality.update({
            "legacy_service_stats_source": legacy_quality.get("source"),
            "legacy_service_stats_source_url": legacy_quality.get("source_url"),
            "legacy_service_stats_latest_match_date": legacy_quality.get("latest_match_date_in_source"),
            "legacy_service_stats_age_days": legacy_quality.get("source_data_age_days"),
            "legacy_service_stats_window_matches": (legacy_profile.get("last_10") or {}).get("matches", 0),
            "matches_with_service_stats": legacy_quality.get("matches_with_service_stats", 0),
        })
        archive_quality["warning"] = (
            str(archive_quality.get("warning") or "")
            + " Las estadísticas de saque y el ranking se conservan desde el archivo histórico anterior; "
            "su muestra no está alineada partido a partido con los resultados exactos de la fuente nueva."
        )
        archived_profile["data_quality"] = archive_quality
        archived_profile["service_return_stats_last_10_matches"] = legacy_service
        archived_profile["ranking_latest_in_window"] = legacy_profile.get("ranking_latest_in_window")
        return archived_profile

    return legacy_profile
