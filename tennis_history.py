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

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 20
MAX_PROFILE_LOOKBACK_DAYS = 730
SUPPORTED_LEAGUES = {"ATP", "WTA"}
BASE_URLS = {
    "ATP": "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master",
    "WTA": "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master",
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
    stats = [_match_stats(row, side) for row, side in matches]
    aces = _sum_available([item["ace"] for item in stats])
    double_faults = _sum_available([item["df"] for item in stats])
    serve_points = _sum_available([item["svpt"] for item in stats])
    first_in = _sum_available([item["1stIn"] for item in stats])
    first_won = _sum_available([item["1stWon"] for item in stats])
    second_won = _sum_available([item["2ndWon"] for item in stats])
    bp_saved = _sum_available([item["bpSaved"] for item in stats])
    bp_faced = _sum_available([item["bpFaced"] for item in stats])
    first_outcomes = _sum_available([item["1stIn"] for item in stats])
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

    # Include enough recent seasons to cover the lookback window. The profile
    # uses event dates strictly earlier than cutoff to prevent target leakage.
    first_year = (cutoff - timedelta(days=int(lookback_days))).year
    rows: list[tuple[date, dict[str, str]]] = []
    years_available: list[int] = []
    for year in range(first_year, cutoff.year + 1):
        annual_rows = load_year(league, year)
        if annual_rows:
            years_available.append(year)
        for row in annual_rows:
            played_on = _match_date(row)
            if played_on and cutoff - timedelta(days=int(lookback_days)) <= played_on < cutoff:
                rows.append((played_on, row))
    rows.sort(key=lambda item: (item[0], str(item[1].get("tourney_id") or ""), str(item[1].get("match_num") or "")))

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
    rankings = []
    for _, row, side in player_matches:
        rank = _integer(row.get("winner_rank" if side == "winner" else "loser_rank"))
        if rank:
            rankings.append(rank)

    return {
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
            "matches_with_service_stats": sum(
                1 for _, row, side in recent_service if _integer(row.get(("w_" if side == "winner" else "l_") + "svpt")) is not None
            ),
            "source": f"Jeff Sackmann {league} historical match CSVs",
            "source_url": BASE_URLS[league],
            "warning": (
                "Las estadísticas de servicio no están disponibles para todos los partidos. "
                "El perfil solo cubre los archivos anuales accesibles y el periodo solicitado."
            ),
        },
    }
