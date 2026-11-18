"""Openfootball CC0 historical results importer for additional competitions.

The importer stores completed results in the existing Supabase archive. It does
not call a live-score API at runtime and does not alter official predictions.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

from football_archive import UPSERT_BATCH_SIZE, get_supabase_client, normalize_team_key

logger = logging.getLogger(__name__)
SOURCE = "openfootball"
BASE_URLS = {
    "europe": "https://raw.githubusercontent.com/openfootball/europe/master",
    "champions": "https://raw.githubusercontent.com/openfootball/champions-league/master",
    "south_america": "https://raw.githubusercontent.com/openfootball/south-america/master",
}
TIMEOUT_SECONDS = 30
MAX_SCORE = 30

OPENFOOTBALL_COMPETITIONS = {
    "PPL": {
        "name": "Primeira Liga", "country": "Portugal", "first_year": 2018,
        "source": "europe", "path": "portugal/{year}-{next_year}_pt1.txt",
    },
    "DED": {
        "name": "Eredivisie", "country": "Netherlands", "first_year": 2018,
        "source": "europe", "path": "netherlands/{year}-{next_year}_nl1.txt",
    },
    "CL": {
        "name": "UEFA Champions League", "country": "Europe", "first_year": 2011,
        "source": "champions", "path": "{year}-{next_year}/cl.txt",
    },
    "BSA": {
        "name": "Brasileirão Série A", "country": "Brazil", "first_year": 2018,
        "source": "south_america", "path": "brazil/{year}_br1.txt",
    },
}

_DATE_LINE = re.compile(
    r"^\s{2,}(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"([A-Za-z]{3})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$"
)
_MATCH_LINE = re.compile(
    r"^\s*(?:\d{1,2}:\d{2}\s+)?(.+?)\s+v\s+(.+?)\s+"
    r"(\d{1,2})-(\d{1,2})(?:\s|$)"
)


def _season_path(config: dict[str, Any], year: int) -> str:
    next_year = year + 1
    return config["path"].format(year=year, next_year=next_year)


def _source_url(competition: str, year: int) -> str:
    config = OPENFOOTBALL_COMPETITIONS[competition]
    return f"{BASE_URLS[config['source']]}/{_season_path(config, year)}"


def parse_openfootball_matches(
    content: str | bytes,
    competition: str,
    season_year: int,
    source_url: str | None = None,
) -> list[dict[str, Any]]:
    """Parse Football.TXT date headings and completed full-time score lines."""
    code = str(competition or "").strip().upper()
    config = OPENFOOTBALL_COMPETITIONS.get(code)
    if not config:
        raise ValueError(f"Unsupported Openfootball competition: {code}")
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="replace")

    current_date = None
    previous_month = None
    rows = []
    for raw_line in content.splitlines():
        date_match = _DATE_LINE.match(raw_line)
        if date_match:
            month_name, day_text, explicit_year = date_match.groups()
            try:
                month = datetime.strptime(month_name, "%b").month
                year = int(explicit_year) if explicit_year else int(season_year)
                if explicit_year is None and previous_month is not None and month < previous_month and previous_month >= 7:
                    year += 1
                current_date = datetime.strptime(
                    f"{year} {month_name} {int(day_text)}", "%Y %b %d"
                ).date().isoformat()
                previous_month = month
            except ValueError:
                current_date = None
            continue

        if not current_date:
            continue
        match = _MATCH_LINE.match(raw_line)
        if not match:
            continue
        home_name, away_name, home_raw, away_raw = match.groups()
        home_name = home_name.strip()
        away_name = away_name.strip()
        # Country tags in international fixtures are source annotations, not
        # part of the club identity used by the archive.
        home_name = re.sub(r"\s+\([A-Z]{3}\)$", "", home_name).strip()
        away_name = re.sub(r"\s+\([A-Z]{3}\)$", "", away_name).strip()
        home_score, away_score = int(home_raw), int(away_raw)
        home_key, away_key = normalize_team_key(home_name), normalize_team_key(away_name)
        if (
            not home_key or not away_key or home_key == away_key
            or home_score > MAX_SCORE or away_score > MAX_SCORE
        ):
            continue

        identity = "|".join((SOURCE, code, str(season_year), current_date, home_key, away_key))
        source_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        rows.append({
            "source_key": source_key,
            "source": SOURCE,
            "source_url": source_url or "",
            "competition_code": code,
            "competition_name": config["name"],
            "season": str(season_year),
            "match_date": current_date,
            "home_team": home_name,
            "home_team_key": home_key,
            "away_team": away_name,
            "away_team_key": away_key,
            "home_score": home_score,
            "away_score": away_score,
            "result": "H" if home_score > away_score else "A" if home_score < away_score else "D",
        })
    return rows


def _download_season(competition: str, year: int) -> list[dict[str, Any]]:
    url = _source_url(competition, year)
    response = requests.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return parse_openfootball_matches(response.content, competition, year, url)


def _store_rows(client, rows: list[dict[str, Any]]) -> int:
    stored = 0
    for offset in range(0, len(rows), UPSERT_BATCH_SIZE):
        batch = rows[offset:offset + UPSERT_BATCH_SIZE]
        if not batch:
            continue
        client.table("football_match_archive").upsert(
            batch, on_conflict="source_key"
        ).execute()
        teams = {}
        for row in batch:
            for side in ("home", "away"):
                key = row.get(f"{side}_team_key")
                name = row.get(f"{side}_team")
                if key and name:
                    teams[(row["competition_code"], key)] = {
                        "competition_code": row["competition_code"],
                        "canonical_team_key": key,
                        "display_name": name,
                    }
        if teams:
            client.table("football_archive_teams").upsert(
                list(teams.values()),
                on_conflict="competition_code,canonical_team_key",
            ).execute()
        stored += len(batch)
    return stored


def sync_openfootball_archive(
    start_year: int = 2011,
    end_year: int | None = None,
    competitions: list[str] | None = None,
) -> dict[str, Any]:
    """Idempotently import completed matches from the Openfootball CC0 datasets."""
    current_year = datetime.now(timezone.utc).year
    end_year = current_year if end_year is None else int(end_year)
    start_year = int(start_year)
    if start_year < 1990 or end_year < start_year or end_year > current_year:
        raise ValueError("Rango de temporadas no válido.")
    selected = [str(code).upper() for code in (competitions or OPENFOOTBALL_COMPETITIONS)]
    unknown = sorted(set(selected) - set(OPENFOOTBALL_COMPETITIONS))
    if unknown:
        raise ValueError(f"Competiciones Openfootball no admitidas: {', '.join(unknown)}")

    client = get_supabase_client()
    totals = {"downloaded": 0, "inserted_or_updated": 0, "available_files": 0, "unavailable_files": 0, "failed_files": 0}
    errors = []
    season_results = []
    for code in selected:
        config = OPENFOOTBALL_COMPETITIONS[code]
        for year in range(max(start_year, config["first_year"]), end_year + 1):
            item = {"competition": code, "season": str(year), "status": "available", "matches": 0}
            try:
                rows = _download_season(code, year)
                item["matches"] = len(rows)
                totals["available_files"] += 1
                totals["downloaded"] += len(rows)
                totals["inserted_or_updated"] += _store_rows(client, rows)
            except requests.HTTPError as exc:
                status_code = getattr(exc.response, "status_code", None)
                if status_code == 404:
                    item["status"] = "unavailable"
                    totals["unavailable_files"] += 1
                else:
                    item["status"] = "failed"
                    totals["failed_files"] += 1
                    errors.append(f"{code}/{year}: HTTP {status_code or 'error'}")
                    logger.warning("Openfootball source failed for %s/%s: %s", code, year, exc)
            except requests.RequestException as exc:
                item["status"] = "failed"
                totals["failed_files"] += 1
                errors.append(f"{code}/{year}: network error")
                logger.warning("Openfootball download failed for %s/%s: %s", code, year, exc)
            except Exception:
                item["status"] = "failed"
                totals["failed_files"] += 1
                errors.append(f"{code}/{year}: storage/import error")
                logger.exception("Openfootball import failed for %s/%s", code, year)
            season_results.append(item)

    coverage = []
    for code in selected:
        items = [item for item in season_results if item["competition"] == code]
        coverage.append({
            "competition": code,
            "seasons_checked": len(items),
            "available_files": sum(item["status"] == "available" for item in items),
            "unavailable_files": sum(item["status"] == "unavailable" for item in items),
            "failed_files": sum(item["status"] == "failed" for item in items),
            "matches_downloaded": sum(item["matches"] for item in items),
            "seasons_with_zero_matches": sum(item["status"] == "available" and item["matches"] == 0 for item in items),
        })
    return {
        "success": totals["failed_files"] == 0,
        "source": SOURCE,
        "start_year": start_year,
        "end_year": end_year,
        "competitions": selected,
        **totals,
        "coverage_by_competition": coverage,
        "season_results": season_results,
        "errors": errors[:50],
    }
