"""Owned football results archive backed by Supabase.

Bulk source: Football-Data.co.uk downloadable CSV files. Runtime reads are
served only from Supabase; no upstream request is made when users view history.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Query

from repository import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/football/archive", tags=["Football archive"])

SOURCE_NAME = "football-data.co.uk"
SOURCE_BASE_URL = "https://www.football-data.co.uk/mmz4281"
REQUEST_TIMEOUT_SECONDS = 30
UPSERT_BATCH_SIZE = 500

# Football-Data.co.uk CSV competition codes for the five major European leagues.
COMPETITIONS = {
    "PL": {"name": "Premier League", "country": "England", "source_code": "E0"},
    "PD": {"name": "LaLiga", "country": "Spain", "source_code": "SP1"},
    "SA": {"name": "Serie A", "country": "Italy", "source_code": "I1"},
    "BL1": {"name": "Bundesliga", "country": "Germany", "source_code": "D1"},
    "FL1": {"name": "Ligue 1", "country": "France", "source_code": "F1"},
}


TEAM_ALIASES = {
    "man utd": "manchester united",
    "man united": "manchester united",
    "manchester utd": "manchester united",
    "man city": "manchester city",
    "ath madrid": "atletico madrid",
    "atletico de madrid": "atletico madrid",
    "spurs": "tottenham hotspur",
    "wolves": "wolverhampton wanderers",
    "newcastle": "newcastle united",
    "west ham": "west ham united",
    "brighton": "brighton and hove albion",
    "leicester": "leicester city",
    "qpr": "queens park rangers",
    "psg": "paris saint germain",
    "inter": "internazionale",
    "ac milan": "milan",
}


def normalize_team_key(value: str) -> str:
    """Normalize accents/suffixes and a small explicit alias list; never fuzzy-match."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token not in {"fc", "afc", "cf", "sc"}]
    key = " ".join(tokens).strip()
    return TEAM_ALIASES.get(key, key)


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def _parse_match_date(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_score(value: Any) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if not number.is_integer() or number < 0 or number > 30:
        return None
    return int(number)


def build_match_payload(row: dict[str, Any], competition: str, season: str) -> dict[str, Any] | None:
    config = COMPETITIONS.get(competition)
    if not config:
        return None
    match_date = _parse_match_date(row.get("Date"))
    home_team = str(row.get("HomeTeam") or "").strip()
    away_team = str(row.get("AwayTeam") or "").strip()
    home_score = _parse_score(row.get("FTHG"))
    away_score = _parse_score(row.get("FTAG"))
    home_key = normalize_team_key(home_team)
    away_key = normalize_team_key(away_team)
    if not match_date or not home_key or not away_key or home_key == away_key:
        return None
    if home_score is None or away_score is None:
        return None

    identity = "|".join((SOURCE_NAME, competition, season, match_date, home_key, away_key))
    source_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return {
        "source_key": source_key,
        "source": SOURCE_NAME,
        "source_url": f"{SOURCE_BASE_URL}/{season}/{config['source_code']}.csv",
        "competition_code": competition,
        "competition_name": config["name"],
        "season": season,
        "match_date": match_date,
        "home_team": home_team,
        "home_team_key": home_key,
        "away_team": away_team,
        "away_team_key": away_key,
        "home_score": home_score,
        "away_score": away_score,
        "result": "H" if home_score > away_score else "A" if home_score < away_score else "D",
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_csv_matches(content: str | bytes, competition: str, season: str) -> list[dict[str, Any]]:
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    rows = []
    for row in reader:
        payload = build_match_payload(row, competition, season)
        if payload:
            rows.append(payload)
    return rows


def _download_season(competition: str, season: str) -> list[dict[str, Any]]:
    config = COMPETITIONS[competition]
    url = f"{SOURCE_BASE_URL}/{season}/{config['source_code']}.csv"
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return parse_csv_matches(response.content, competition, season)


def sync_football_archive(
    start_year: int = 2000,
    end_year: int | None = None,
    competitions: list[str] | None = None,
) -> dict[str, Any]:
    """Import completed league results; idempotent by deterministic source_key."""
    if end_year is None:
        end_year = datetime.now(timezone.utc).year
    if start_year < 1990 or end_year < start_year or end_year > datetime.now(timezone.utc).year:
        raise ValueError("Rango de temporadas no válido.")
    selected = [code.upper() for code in (competitions or list(COMPETITIONS))]
    unknown = sorted(set(selected) - set(COMPETITIONS))
    if unknown:
        raise ValueError(f"Competiciones no admitidas: {', '.join(unknown)}")

    client = get_supabase_client()
    totals = {"downloaded": 0, "inserted_or_updated": 0, "unavailable_files": 0, "failed_files": 0}
    errors: list[str] = []
    for year in range(start_year, end_year + 1):
        season = season_code(year)
        for competition in selected:
            try:
                rows = _download_season(competition, season)
                totals["downloaded"] += len(rows)
                for offset in range(0, len(rows), UPSERT_BATCH_SIZE):
                    batch = rows[offset:offset + UPSERT_BATCH_SIZE]
                    if batch:
                        client.table("football_match_archive").upsert(
                            batch, on_conflict="source_key"
                        ).execute()
                        totals["inserted_or_updated"] += len(batch)
                logger.info("Football archive %s %s: %s matches", competition, season, len(rows))
            except requests.HTTPError as exc:
                if getattr(exc.response, "status_code", None) == 404:
                    totals["unavailable_files"] += 1
                    continue
                totals["failed_files"] += 1
                errors.append(f"{competition}/{season}: HTTP {getattr(exc.response, 'status_code', 'error')}")
                logger.warning("Football archive source failed for %s/%s: %s", competition, season, exc)
            except requests.RequestException as exc:
                totals["failed_files"] += 1
                errors.append(f"{competition}/{season}: network error")
                logger.warning("Football archive download failed for %s/%s: %s", competition, season, exc)
            except Exception as exc:
                totals["failed_files"] += 1
                errors.append(f"{competition}/{season}: storage/import error")
                logger.exception("Football archive import failed for %s/%s", competition, season)

    return {
        "success": totals["failed_files"] == 0,
        "source": SOURCE_NAME,
        "start_year": start_year,
        "end_year": end_year,
        "competitions": selected,
        **totals,
        "errors": errors[:50],
    }


def _client_or_503():
    try:
        return get_supabase_client()
    except Exception as exc:
        logger.exception("Football archive storage is unavailable")
        raise HTTPException(status_code=503, detail="El histórico propio no está disponible temporalmente.") from exc


def _row_result(row: dict[str, Any], home_key: str) -> dict[str, Any]:
    home_score = int(row["home_score"])
    away_score = int(row["away_score"])
    winner = "draw" if home_score == away_score else "home" if home_score > away_score else "away"
    return {
        "id": row["source_key"],
        "date": row["match_date"],
        "season": row["season"],
        "competition": row["competition_name"],
        "competition_code": row["competition_code"],
        "home_team": row["home_team"],
        "home_team_key": row["home_team_key"],
        "away_team": row["away_team"],
        "away_team_key": row["away_team_key"],
        "home_score": home_score,
        "away_score": away_score,
        "total_goals": home_score + away_score,
        "winner": winner,
        "result_source": row["source"],
        "_selected_home_result": (
            winner if row["home_team_key"] == home_key
            else "away" if winner == "home" else "home" if winner == "away" else "draw"
        ),
        "_selected_home_goals": home_score if row["home_team_key"] == home_key else away_score,
        "_selected_away_goals": away_score if row["home_team_key"] == home_key else home_score,
    }


@router.get("/competitions")
def archive_competitions():
    """Return locally stored league coverage; this endpoint never contacts a data provider."""
    client = _client_or_503()
    result = []
    try:
        for code, config in COMPETITIONS.items():
            count_result = client.table("football_match_archive").select(
                "source_key", count="exact"
            ).eq("competition_code", code).limit(1).execute()
            # PostgREST commonly caps a response at 1,000 rows. Paginate the
            # lightweight season column so old seasons are not silently omitted.
            season_values = set()
            offset = 0
            while True:
                season_rows = client.table("football_match_archive").select(
                    "season"
                ).eq("competition_code", code).order("season").range(
                    offset, offset + 999
                ).execute().data or []
                season_values.update(
                    str(row["season"]) for row in season_rows if row.get("season")
                )
                if len(season_rows) < 1000:
                    break
                offset += 1000
            seasons = sorted(season_values)
            result.append({
                "code": code,
                "name": config["name"],
                "country": config["country"],
                "stored_matches": int(count_result.count or 0),
                "seasons": seasons,
                "first_season": seasons[0] if seasons else None,
                "last_season": seasons[-1] if seasons else None,
            })
    except Exception as exc:
        logger.exception("Could not read football archive competition coverage")
        raise HTTPException(status_code=503, detail="No se pudo consultar la cobertura del histórico propio.") from exc
    return {"success": True, "source": SOURCE_NAME, "provider_calls": 0, "competitions": result}


@router.get("/head-to-head")
def archive_head_to_head(
    competition: str = Query(...),
    home_team: str = Query(..., min_length=2, max_length=100),
    away_team: str = Query(..., min_length=2, max_length=100),
    kickoff_at: str | None = None,
    limit: int = Query(20, ge=1, le=100),
):
    code = competition.strip().upper()
    if code not in COMPETITIONS:
        raise HTTPException(status_code=400, detail=f"Competición no admitida. Usa: {', '.join(COMPETITIONS)}.")
    home_key, away_key = normalize_team_key(home_team), normalize_team_key(away_team)
    if not home_key or not away_key or home_key == away_key:
        raise HTTPException(status_code=400, detail="Los equipos deben ser distintos y tener nombres válidos.")
    cutoff = None
    if kickoff_at:
        try:
            cutoff = datetime.fromisoformat(kickoff_at.replace("Z", "+00:00")).date().isoformat()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="kickoff_at no es una fecha ISO 8601 válida.") from exc

    client = _client_or_503()
    try:
        # Search every imported league so direct meetings in another covered
        # competition are retained, matching the previous cross-competition H2H intent.
        query = client.table("football_match_archive").select("*").or_(
            f"home_team_key.eq.{home_key},away_team_key.eq.{home_key}"
        ).order(
            "match_date", desc=True
        ).limit(1000)
        rows = query.execute().data or []
    except Exception as exc:
        logger.exception("Could not query football archive H2H")
        raise HTTPException(status_code=503, detail="No se pudo consultar el histórico almacenado.") from exc

    meetings = [
        _row_result(row, home_key) for row in rows
        if {row.get("home_team_key"), row.get("away_team_key")} == {home_key, away_key}
        and (cutoff is None or str(row.get("match_date") or "") < cutoff)
    ]
    meetings.sort(key=lambda row: row["date"], reverse=True)
    count = len(meetings)
    summary = {
        "home_team_wins": sum(row["_selected_home_result"] == "home" for row in meetings),
        "draws": sum(row["_selected_home_result"] == "draw" for row in meetings),
        "away_team_wins": sum(row["_selected_home_result"] == "away" for row in meetings),
        "home_team_goals": sum(row["_selected_home_goals"] for row in meetings),
        "away_team_goals": sum(row["_selected_away_goals"] for row in meetings),
        "average_home_team_goals": round(sum(row["_selected_home_goals"] for row in meetings) / count, 3) if count else None,
        "average_away_team_goals": round(sum(row["_selected_away_goals"] for row in meetings) / count, 3) if count else None,
        "average_total_goals": round(sum(row["total_goals"] for row in meetings) / count, 3) if count else None,
        "both_teams_scored_count": sum(row["home_score"] > 0 and row["away_score"] > 0 for row in meetings),
        "over_2_5_count": sum(row["total_goals"] >= 3 for row in meetings),
        "under_2_5_count": sum(row["total_goals"] <= 2 for row in meetings),
    }
    clean_meetings = [{key: value for key, value in row.items() if not key.startswith("_")} for row in meetings[:limit]]
    return {
        "success": True,
        "provider": "Sports Predictor · Supabase archive",
        "source": SOURCE_NAME,
        "competition": code,
        "history_scope": "Histórico propio almacenado en las cinco ligas cubiertas. Incluye enfrentamientos de cualquier liga importada; no representa necesariamente todos los torneos ni todos los partidos disputados.",
        "availability": "available" if count else "no_data",
        "history_strategy": "owned_local_archive",
        "competitions_in_sample": sorted({row["competition"] for row in clean_meetings}),
        "teams": {"home": {"name": home_team, "key": home_key}, "away": {"name": away_team, "key": away_key}},
        "sample_size": count,
        "summary": summary,
        "meetings": clean_meetings,
        "returned_matches": len(clean_meetings),
        "provider_calls": 0,
    }


@router.get("/competition/{competition}")
def archive_competition_matches(
    competition: str,
    season: str | None = None,
    team: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    code = competition.strip().upper()
    if code not in COMPETITIONS:
        raise HTTPException(status_code=400, detail=f"Competición no admitida. Usa: {', '.join(COMPETITIONS)}.")
    if season and not re.fullmatch(r"\d{4}", season):
        raise HTTPException(status_code=400, detail="season debe tener formato de cuatro dígitos, por ejemplo 2526.")
    client = _client_or_503()
    try:
        query = client.table("football_match_archive").select("*").eq(
            "competition_code", code
        )
        if season:
            query = query.eq("season", season)
        if team:
            key = normalize_team_key(team)
            query = query.or_(f"home_team_key.eq.{key},away_team_key.eq.{key}")
        result = query.order("match_date", desc=True).limit(limit).execute()
        rows = result.data or []
    except Exception as exc:
        logger.exception("Could not query football competition archive")
        raise HTTPException(status_code=503, detail="No se pudo consultar el histórico de la competición.") from exc
    return {
        "success": True,
        "provider": "Sports Predictor · Supabase archive",
        "source": SOURCE_NAME,
        "competition": code,
        "competition_name": COMPETITIONS[code]["name"],
        "season": season,
        "sample_size": len(rows),
        "limit": limit,
        "provider_calls": 0,
        "matches": [{
            "id": row["source_key"], "date": row["match_date"], "season": row["season"],
            "home_team": row["home_team"], "away_team": row["away_team"],
            "home_score": row["home_score"], "away_score": row["away_score"],
            "competition": row["competition_name"], "source": row["source"],
        } for row in rows],
    }
