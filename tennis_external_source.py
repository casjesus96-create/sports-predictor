"""Independent, read-only coverage audit for Valuebetennis match CSVs.

This adapter intentionally does not merge external rows into the Elo dataset.
It verifies date-level coverage and source schema first; identity reconciliation,
licensing attribution, and duplicate analysis must pass before model evaluation.
Source terms: CC BY 4.0, with attribution required.
"""
from __future__ import annotations

import csv
import io
import logging
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any

import requests

logger = logging.getLogger(__name__)
SOURCE_URL = "https://www.valuebetennis.com/donnees.htm"
CSV_URL_TEMPLATE = "https://www.valuebetennis.com/datasets/valuebetennis-matchs-{year}.csv"
SOURCE_LICENSE = "CC BY 4.0"
SOURCE_ATTRIBUTION = (
    "Valuebetennis, Résultats et cotes de tennis depuis 2021, "
    "https://www.valuebetennis.com/donnees.htm"
)
TIMEOUT_SECONDS = 20
SUPPORTED_LEAGUES = {"ATP", "WTA"}
MAX_AUDIT_DAYS = 366
HEADERS = {"User-Agent": "Sports-Predictor-Tennis-Source-Audit/1.0", "Accept": "text/csv"}


class ExternalTennisSourceError(RuntimeError):
    """Raised when the external CSV cannot be safely read."""


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Las fechas deben usar el formato YYYY-MM-DD.") from exc


def _match_day(value: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        # The publisher documents this field as the match date/time in UTC.
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.date()
    except ValueError:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    return None


def _read_csv(text: str) -> list[dict[str, str]]:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ExternalTennisSourceError("El CSV externo no contiene encabezados.")
    rows = [dict(row) for row in reader]
    normalized_headers = {str(key or "").strip().casefold() for key in reader.fieldnames}
    required = {
        "date", "genre", "categorie", "joueur1", "joueur2",
        "joueur1_id", "joueur2_id", "vainqueur_id",
    }
    if not required.issubset(normalized_headers):
        raise ExternalTennisSourceError(
            "El esquema del CSV externo cambió o no contiene las columnas obligatorias."
        )
    return rows


@lru_cache(maxsize=8)
def load_external_year(year: int) -> tuple[dict[str, str], ...]:
    """Fetch and cache one annual public CSV; never treat a failed fetch as empty."""
    if year < 2021 or year > datetime.now(timezone.utc).year:
        raise ValueError("El año solicitado está fuera del rango de la fuente externa.")
    try:
        response = requests.get(
            CSV_URL_TEMPLATE.format(year=year),
            headers=HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return tuple(_read_csv(response.text))
    except requests.RequestException as exc:
        logger.warning("No se pudo cargar el CSV externo de tenis %s: %s", year, exc)
        raise ExternalTennisSourceError(
            f"No se pudo consultar el CSV externo de tenis para {year}."
        ) from exc


def audit_external_coverage(
    league: str,
    start_date: str | date,
    end_date: str | date,
) -> dict[str, Any]:
    """Report source coverage only; does not merge, deduplicate, or score matches."""
    selected_league = str(league or "").strip().upper()
    if selected_league not in SUPPORTED_LEAGUES:
        raise ValueError("league debe ser ATP o WTA.")
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if end < start:
        raise ValueError("end_date debe ser igual o posterior a start_date.")
    if (end - start).days + 1 > MAX_AUDIT_DAYS:
        raise ValueError("El periodo de auditoría no puede superar 366 días.")
    if start.year < 2021:
        raise ValueError("La fuente externa de cobertura comienza en 2021.")

    monthly: dict[str, int] = defaultdict(int)
    category_monthly: dict[str, Counter[str]] = defaultdict(Counter)
    invalid_dates = 0
    invalid_results = 0
    rows_seen = 0
    valid_dates: list[date] = []
    for year in range(start.year, end.year + 1):
        for row in load_external_year(year):
            rows_seen += 1
            if str(row.get("genre") or "").strip().upper() != selected_league:
                continue
            played_on = _match_day(row.get("date", ""))
            if played_on is None:
                invalid_dates += 1
                continue
            if not start <= played_on <= end:
                continue
            player1_id = str(row.get("joueur1_id") or "").strip()
            player2_id = str(row.get("joueur2_id") or "").strip()
            winner_id = str(row.get("vainqueur_id") or "").strip()
            if not player1_id or not player2_id or winner_id not in {player1_id, player2_id}:
                invalid_results += 1
                continue
            month = played_on.strftime("%Y-%m")
            category = str(row.get("categorie") or "unknown").strip() or "unknown"
            monthly[month] += 1
            category_monthly[month][category] += 1
            valid_dates.append(played_on)

    monthly_breakdown = []
    cursor = start.replace(day=1)
    while cursor <= end:
        key = cursor.strftime("%Y-%m")
        monthly_breakdown.append({
            "month": key,
            "valid_matches": monthly.get(key, 0),
            "categories": dict(sorted(category_monthly[key].items())),
        })
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)

    return {
        "success": True,
        "status": "source_audit_only",
        "model_status": "research_only",
        "league": selected_league,
        "requested_window": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "source": {
            "name": "Valuebetennis historical match CSV",
            "url": SOURCE_URL,
            "csv_url_template": CSV_URL_TEMPLATE,
            "license": SOURCE_LICENSE,
            "attribution": SOURCE_ATTRIBUTION,
            "date_semantics": "match date/time supplied in UTC",
        },
        "coverage": {
            "rows_seen_across_loaded_year_files": rows_seen,
            "valid_matches_in_window": sum(monthly.values()),
            "coverage_start_date": min(valid_dates).isoformat() if valid_dates else None,
            "coverage_end_date": max(valid_dates).isoformat() if valid_dates else None,
            "months_with_matches": sum(item["valid_matches"] > 0 for item in monthly_breakdown),
            "months_without_matches": [item["month"] for item in monthly_breakdown if item["valid_matches"] == 0],
            "invalid_dates_for_selected_league": invalid_dates,
            "invalid_results_in_window": invalid_results,
            "monthly_breakdown": monthly_breakdown,
        },
        "limitations": [
            "Audit only: external rows are not merged into the existing historical dataset.",
            "The source covers multiple competition categories; category scope must be reconciled before model evaluation.",
            "Player identities, duplicate matches, and source-to-source conflicts have not yet been reconciled.",
            "Attribution under CC BY 4.0 is required.",
        ],
    }
