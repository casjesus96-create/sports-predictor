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
from pydantic import BaseModel, Field

from repository import get_supabase_client
from football_backtest import run_chronological_backtest
from football_research_validation import build_candidate_validation

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
    # Canonical keys match the names already persisted by Football-Data.co.uk.
    # Calendar/provider display names may include the club suffixes.
    "leeds united": "leeds",
    "hull city": "hull",
    "tottenham hotspur": "tottenham",
    "spurs": "tottenham",
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
                        teams = {}
                        for row in batch:
                            for side in ("home", "away"):
                                key = row.get(f"{side}_team_key")
                                name = row.get(f"{side}_team")
                                if key and name:
                                    teams[(competition, key)] = {
                                        "competition_code": competition,
                                        "canonical_team_key": key,
                                        "display_name": name,
                                    }
                        if teams:
                            client.table("football_archive_teams").upsert(
                                list(teams.values()),
                                on_conflict="competition_code,canonical_team_key",
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



class TeamAliasRequest(BaseModel):
    competition_code: str = Field(min_length=2, max_length=8)
    alias_name: str = Field(min_length=2, max_length=100)
    canonical_team_key: str = Field(min_length=2, max_length=100)


def _safe_team_search(value: str) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    raw = re.sub(r"[^a-zA-Z0-9 ]+", " ", raw)
    return " ".join(raw.split())[:80]


def _resolve_team_identity(client, competition: str, original_name: str) -> tuple[str, str]:
    """Use verified competition aliases, then deterministic normalization; never fuzzy-match."""
    normalized = normalize_team_key(original_name)
    try:
        result = client.table("football_team_aliases").select(
            "canonical_team_key"
        ).eq("competition_code", competition).eq(
            "alias_key", normalized
        ).limit(2).execute()
        aliases = result.data or []
        if len(aliases) == 1:
            return str(aliases[0]["canonical_team_key"]), "verified_alias"
        if len(aliases) > 1:
            return normalized, "ambiguous_alias"
    except Exception:
        logger.warning("Football team alias registry unavailable; using deterministic normalization")

    try:
        known = client.table("football_archive_teams").select(
            "canonical_team_key"
        ).eq("competition_code", competition).eq(
            "canonical_team_key", normalized
        ).limit(1).execute()
        if known.data:
            return normalized, "exact"
        unresolved = client.table("football_unresolved_team_names").select(
            "id,seen_count"
        ).eq("provider", "football-data.org").eq(
            "competition_code", competition
        ).eq("normalized_key", normalized).limit(1).execute()
        existing = unresolved.data or []
        if existing:
            item = existing[0]
            client.table("football_unresolved_team_names").update({
                "original_name": str(original_name)[:100],
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "seen_count": int(item.get("seen_count") or 0) + 1,
            }).eq("id", item["id"]).execute()
        else:
            client.table("football_unresolved_team_names").insert({
                "provider": "football-data.org",
                "competition_code": competition,
                "original_name": str(original_name)[:100],
                "normalized_key": normalized,
            }).execute()
    except Exception:
        logger.warning("Could not consult/log football team identity for %s", original_name)
    return normalized, "unverified"


@router.get("/teams/lookup")
def archive_team_lookup(
    competition: str = Query(...),
    query: str = Query(..., min_length=2, max_length=100),
):
    """Search the owned archive for a user-confirmable canonical team."""
    code = competition.strip().upper()
    if code not in COMPETITIONS:
        raise HTTPException(status_code=400, detail="Competición no admitida.")
    search_text = _safe_team_search(query)
    if len(search_text) < 2:
        raise HTTPException(status_code=400, detail="Escribe al menos dos caracteres válidos.")
    normalized = normalize_team_key(search_text)
    client = _client_or_503()
    try:
        filters = (
            f"display_name.ilike.%{search_text}%,"
            f"canonical_team_key.eq.{normalized},"
            f"canonical_team_key.ilike.%{normalized}%"
        )
        result = client.table("football_archive_teams").select(
            "canonical_team_key,display_name,competition_code"
        ).eq("competition_code", code).or_(
            filters
        ).order("display_name").limit(50).execute()
        rows = result.data or []
    except Exception as exc:
        logger.exception("Could not search football archive teams")
        raise HTTPException(status_code=503, detail="No se pudieron buscar equipos en el archivo.") from exc
    unique = {}
    for row in rows:
        key = str(row.get("canonical_team_key") or "")
        if key:
            unique[key] = {
                "canonical_team_key": key,
                "display_name": row.get("display_name") or key,
                "competition_code": code,
            }
    return {
        "success": True, "competition": code, "query": query,
        "candidates": list(unique.values()), "count": len(unique),
        "provider_calls": 0, "writes": 0,
    }


@router.post("/teams/aliases")
def archive_confirm_team_alias(payload: TeamAliasRequest):
    """Persist an alias only after explicit user selection of a real archive team."""
    code = payload.competition_code.strip().upper()
    if code not in COMPETITIONS:
        raise HTTPException(status_code=400, detail="Competición no admitida.")
    alias_key = normalize_team_key(payload.alias_name)
    target_key = str(payload.canonical_team_key).strip()
    if not alias_key or not target_key or alias_key == target_key:
        raise HTTPException(status_code=400, detail="El alias debe ser distinto de la clave canónica.")
    client = _client_or_503()
    try:
        target = client.table("football_archive_teams").select(
            "canonical_team_key"
        ).eq("competition_code", code).eq(
            "canonical_team_key", target_key
        ).limit(1).execute()
        if not target.data:
            raise HTTPException(status_code=404, detail="El equipo elegido no existe en el histórico de esta competición.")
        existing = client.table("football_team_aliases").select(
            "canonical_team_key"
        ).eq("competition_code", code).eq("alias_key", alias_key).limit(2).execute()
        rows = existing.data or []
        if rows:
            if len(rows) == 1 and rows[0].get("canonical_team_key") == target_key:
                return {"success": True, "created": False, "alias": payload.alias_name, "canonical_team_key": target_key}
            raise HTTPException(status_code=409, detail="Este nombre ya está asociado a otro equipo. No se modificó la asociación existente.")
        client.table("football_team_aliases").insert({
            "competition_code": code, "alias_key": alias_key,
            "alias_name": payload.alias_name.strip(),
            "canonical_team_key": target_key,
            "created_by": "manual_user_confirmation",
        }).execute()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not persist confirmed football team alias")
        raise HTTPException(status_code=503, detail="No se pudo guardar el alias confirmado.") from exc
    return {
        "success": True, "created": True, "alias": payload.alias_name.strip(),
        "alias_key": alias_key, "canonical_team_key": target_key,
        "competition_code": code, "scope": "competition",
    }


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
        "_selected_home_venue": "home" if row["home_team_key"] == home_key else "away",
        "_selected_away_venue": "away" if row["home_team_key"] == home_key else "home",
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




def _percentage(count: int, sample_size: int) -> float | None:
    return round(count * 100 / sample_size, 1) if sample_size else None


def _venue_record(meetings: list[dict[str, Any]], team_side: str, venue: str) -> dict[str, Any]:
    goals_for_key = "_selected_home_goals" if team_side == "home" else "_selected_away_goals"
    goals_against_key = "_selected_away_goals" if team_side == "home" else "_selected_home_goals"
    venue_key = "_selected_home_venue" if team_side == "home" else "_selected_away_venue"
    selected = [row for row in meetings if row.get(venue_key) == venue]
    if team_side == "home":
        wins = sum(row["_selected_home_result"] == "home" for row in selected)
    else:
        wins = sum(row["_selected_home_result"] == "away" for row in selected)
    draws = sum(row["_selected_home_result"] == "draw" for row in selected)
    losses = len(selected) - wins - draws
    goals_for = sum(row[goals_for_key] for row in selected)
    goals_against = sum(row[goals_against_key] for row in selected)
    return {
        "matches": len(selected), "wins": wins, "draws": draws, "losses": losses,
        "goals_for": goals_for, "goals_against": goals_against,
        "average_goals_for": round(goals_for / len(selected), 3) if selected else None,
        "average_goals_against": round(goals_against / len(selected), 3) if selected else None,
        "win_percentage": _percentage(wins, len(selected)),
    }


def _summarize_head_to_head(meetings: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate descriptive H2H frequencies from completed archived matches."""
    count = len(meetings)
    home_wins = sum(row["_selected_home_result"] == "home" for row in meetings)
    draws = sum(row["_selected_home_result"] == "draw" for row in meetings)
    away_wins = sum(row["_selected_home_result"] == "away" for row in meetings)
    both_scored = sum(row["home_score"] > 0 and row["away_score"] > 0 for row in meetings)
    over_1_5 = sum(row["total_goals"] >= 2 for row in meetings)
    over_2_5 = sum(row["total_goals"] >= 3 for row in meetings)
    over_3_5 = sum(row["total_goals"] >= 4 for row in meetings)
    home_goals = sum(row["_selected_home_goals"] for row in meetings)
    away_goals = sum(row["_selected_away_goals"] for row in meetings)
    total_goals = sum(row["total_goals"] for row in meetings)
    home_clean = sum(row["_selected_away_goals"] == 0 for row in meetings)
    away_clean = sum(row["_selected_home_goals"] == 0 for row in meetings)
    return {
        "home_team_wins": home_wins, "home_team_wins_percentage": _percentage(home_wins, count),
        "draws": draws, "draws_percentage": _percentage(draws, count),
        "away_team_wins": away_wins, "away_team_wins_percentage": _percentage(away_wins, count),
        "home_team_goals": home_goals, "away_team_goals": away_goals,
        "average_home_team_goals": round(home_goals / count, 3) if count else None,
        "average_away_team_goals": round(away_goals / count, 3) if count else None,
        "average_total_goals": round(total_goals / count, 3) if count else None,
        "both_teams_scored_count": both_scored,
        "both_teams_scored_percentage": _percentage(both_scored, count),
        "over_1_5_count": over_1_5, "over_1_5_percentage": _percentage(over_1_5, count),
        "over_2_5_count": over_2_5, "over_2_5_percentage": _percentage(over_2_5, count),
        "over_3_5_count": over_3_5, "over_3_5_percentage": _percentage(over_3_5, count),
        "under_1_5_count": count - over_1_5, "under_1_5_percentage": _percentage(count - over_1_5, count),
        "under_2_5_count": count - over_2_5, "under_2_5_percentage": _percentage(count - over_2_5, count),
        "under_3_5_count": count - over_3_5, "under_3_5_percentage": _percentage(count - over_3_5, count),
        # Counts refer to the selected teams, not historical home/away venue.
        # Legacy keys remain available for backward compatibility.
        "home_team_clean_sheets": home_clean, "away_team_clean_sheets": away_clean,
        "home_team_clean_sheets_percentage": _percentage(home_clean, count),
        "away_team_clean_sheets_percentage": _percentage(away_clean, count),
        "home_team_failed_to_score": away_clean, "away_team_failed_to_score": home_clean,
        "home_team_failed_to_score_count": away_clean,
        "away_team_failed_to_score_count": home_clean,
        "home_team_failed_to_score_percentage": _percentage(away_clean, count),
        "away_team_failed_to_score_percentage": _percentage(home_clean, count),
        "venue_split": {
            "home_team": {"at_home": _venue_record(meetings, "home", "home"), "away": _venue_record(meetings, "home", "away")},
            "away_team": {"at_home": _venue_record(meetings, "away", "home"), "away": _venue_record(meetings, "away", "away")},
        },
    }


@router.get("/head-to-head")
def archive_head_to_head(
    competition: str = Query(...),
    home_team: str = Query(..., min_length=2, max_length=100),
    away_team: str = Query(..., min_length=2, max_length=100),
    kickoff_at: str | None = None,
    # Plain default also supports direct calls outside FastAPI.
    limit: int = 20,
    # Plain default keeps direct Python calls compatible with unit tests;
    # FastAPI still exposes this parameter as an optional query string.
    scope: str = "all",
):
    code = competition.strip().upper()
    scope = scope.strip().lower()
    if scope not in {"all", "competition"}:
        raise HTTPException(status_code=400, detail="scope debe ser 'all' o 'competition'.")
    if code not in COMPETITIONS:
        raise HTTPException(status_code=400, detail=f"Competición no admitida. Usa: {', '.join(COMPETITIONS)}.")
    client = _client_or_503()
    home_key, home_resolution = _resolve_team_identity(client, code, home_team)
    away_key, away_resolution = _resolve_team_identity(client, code, away_team)
    if not home_key or not away_key or home_key == away_key:
        raise HTTPException(status_code=400, detail="Los equipos deben ser distintos y tener nombres válidos.")
    cutoff = None
    if kickoff_at:
        try:
            cutoff = datetime.fromisoformat(kickoff_at.replace("Z", "+00:00")).date().isoformat()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="kickoff_at no es una fecha ISO 8601 válida.") from exc

    try:
        # Query the exact unordered pair in one database request. This avoids
        # scanning the first 1,000 matches for one club and then filtering in Python,
        # which could silently hide older direct meetings.
        pair_filter = (
            f"and(home_team_key.eq.{home_key},away_team_key.eq.{away_key}),"
            f"and(home_team_key.eq.{away_key},away_team_key.eq.{home_key})"
        )
        query = client.table("football_match_archive").select("*").or_(pair_filter)
        if scope == "competition":
            query = query.eq("competition_code", code)
        query = query.order("match_date", desc=True).limit(1000)
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
    summary = _summarize_head_to_head(meetings)
    clean_meetings = [{key: value for key, value in row.items() if not key.startswith("_")} for row in meetings[:limit]]
    return {
        "success": True,
        "provider": "Sports Predictor · Supabase archive",
        "source": SOURCE_NAME,
        "competition": code,
        "history_scope": (
            f"Solo {COMPETITIONS[code]['name']}."
            if scope == "competition"
            else "Todas las competiciones disponibles en el archivo propio de cinco ligas; no representa necesariamente todos los torneos ni todos los partidos disputados."
        ),
        "scope": scope,
        "availability": "available" if count else "no_data",
        "history_strategy": "owned_local_archive",
        "competitions_in_sample": sorted({row["competition"] for row in meetings}),
        "teams": {
            "home": {"name": home_team, "key": home_key, "resolution": home_resolution},
            "away": {"name": away_team, "key": away_key, "resolution": away_resolution},
        },
        "sample_size": count,
        "summary": summary,
        "meetings": clean_meetings,
        "returned_matches": len(clean_meetings),
        "provider_calls": 0,
    }


def _team_form_match(row: dict[str, Any], team_key: str) -> dict[str, Any]:
    """Orient one archived match from the selected team's perspective."""
    is_home = row.get("home_team_key") == team_key
    goals_for = int(row["home_score"] if is_home else row["away_score"])
    goals_against = int(row["away_score"] if is_home else row["home_score"])
    result = "W" if goals_for > goals_against else "L" if goals_for < goals_against else "D"
    return {
        "id": row.get("source_key"),
        "date": row.get("match_date"),
        "competition": row.get("competition_name"),
        "opponent": row.get("away_team") if is_home else row.get("home_team"),
        "venue": "home" if is_home else "away",
        "goals_for": goals_for,
        "goals_against": goals_against,
        "result": result,
        "points": 3 if result == "W" else 1 if result == "D" else 0,
        "total_goals": goals_for + goals_against,
    }


def _team_form_venue_summary(matches: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(matches)
    wins = sum(item["result"] == "W" for item in matches)
    draws = sum(item["result"] == "D" for item in matches)
    losses = sum(item["result"] == "L" for item in matches)
    goals_for = sum(item["goals_for"] for item in matches)
    goals_against = sum(item["goals_against"] for item in matches)
    return {
        "matches": count,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "points": sum(item["points"] for item in matches),
        "goals_for": goals_for,
        "goals_against": goals_against,
        "average_goals_for": round(goals_for / count, 3) if count else None,
        "average_goals_against": round(goals_against / count, 3) if count else None,
        "win_percentage": _percentage(wins, count),
        "clean_sheets": sum(item["goals_against"] == 0 for item in matches),
        "failed_to_score": sum(item["goals_for"] == 0 for item in matches),
    }




def _summarize_venue_sample(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptive team-perspective outcomes and goal markets for one venue sample."""
    count = len(matches)
    summary = _team_form_venue_summary(matches)
    over_counts = {"1_5": sum(item["total_goals"] >= 2 for item in matches), "2_5": sum(item["total_goals"] >= 3 for item in matches), "3_5": sum(item["total_goals"] >= 4 for item in matches)}
    btts = sum(item["goals_for"] > 0 and item["goals_against"] > 0 for item in matches)
    result = {**summary, "both_teams_scored": btts, "both_teams_scored_percentage": _percentage(btts, count), "average_total_goals": round(sum(item["total_goals"] for item in matches) / count, 3) if count else None, "sample_start": min((item.get("date") for item in matches if item.get("date")), default=None), "sample_end": max((item.get("date") for item in matches if item.get("date")), default=None)}
    for line, over_count in over_counts.items():
        result[f"over_{line}"] = over_count
        result[f"over_{line}_percentage"] = _percentage(over_count, count)
        result[f"under_{line}"] = count - over_count
        result[f"under_{line}_percentage"] = _percentage(count - over_count, count)
    return result


def _summarize_venue_windows(matches: list[dict[str, Any]], venue: str) -> dict[str, Any]:
    selected = [item for item in matches if item.get("venue") == venue]
    return {str(size): {"requested_matches": size, "sample_complete": len(selected[:size]) == size, **_summarize_venue_sample(selected[:size])} for size in (5, 10, 15)}

def _summarize_team_form(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Return descriptive 5/10/15-match windows; never pad incomplete samples."""
    windows: dict[str, Any] = {}
    for size in (5, 10, 15):
        selected = matches[:size]
        count = len(selected)
        record = _team_form_venue_summary(selected)
        both_scored = sum(item["goals_for"] > 0 and item["goals_against"] > 0 for item in selected)
        over_1_5 = sum(item["total_goals"] >= 2 for item in selected)
        over_2_5 = sum(item["total_goals"] >= 3 for item in selected)
        over_3_5 = sum(item["total_goals"] >= 4 for item in selected)
        home_matches = [item for item in selected if item["venue"] == "home"]
        away_matches = [item for item in selected if item["venue"] == "away"]
        # The database rows arrive newest-first; show form oldest-to-newest.
        sequence = [item["result"] for item in reversed(selected)]
        windows[str(size)] = {
            **record,
            "requested_matches": size,
            "sample_complete": count == size,
            "form_sequence": sequence,
            "both_teams_scored": both_scored,
            "both_teams_scored_percentage": _percentage(both_scored, count),
            "over_1_5": over_1_5,
            "over_1_5_percentage": _percentage(over_1_5, count),
            "over_2_5": over_2_5,
            "over_2_5_percentage": _percentage(over_2_5, count),
            "over_3_5": over_3_5,
            "over_3_5_percentage": _percentage(over_3_5, count),
            "under_1_5": count - over_1_5,
            "under_1_5_percentage": _percentage(count - over_1_5, count),
            "under_2_5": count - over_2_5,
            "under_2_5_percentage": _percentage(count - over_2_5, count),
            "under_3_5": count - over_3_5,
            "under_3_5_percentage": _percentage(count - over_3_5, count),
            "goals_for_distribution": _goal_bucket_counts([item["goals_for"] for item in selected], count),
            "goals_against_distribution": _goal_bucket_counts([item["goals_against"] for item in selected], count),
            "venue_market_patterns": {
                "at_home": {
                    "matches": len(home_matches),
                    "over_2_5": sum(item["total_goals"] >= 3 for item in home_matches),
                    "both_teams_scored": sum(item["goals_for"] > 0 and item["goals_against"] > 0 for item in home_matches),
                },
                "away": {
                    "matches": len(away_matches),
                    "over_2_5": sum(item["total_goals"] >= 3 for item in away_matches),
                    "both_teams_scored": sum(item["goals_for"] > 0 and item["goals_against"] > 0 for item in away_matches),
                },
            },
            "venue_split": {
                "at_home": _team_form_venue_summary([item for item in selected if item["venue"] == "home"]),
                "away": _team_form_venue_summary([item for item in selected if item["venue"] == "away"]),
            },
        }
    return windows




def _goal_bucket_counts(values: list[int], count: int) -> dict[str, Any]:
    buckets = {
        "0": sum(value == 0 for value in values),
        "1": sum(value == 1 for value in values),
        "2": sum(value == 2 for value in values),
        "3_plus": sum(value >= 3 for value in values),
    }
    return {
        key: {"count": value, "percentage": _percentage(value, count)}
        for key, value in buckets.items()
    }


def _summarize_market_sample(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptive goal-market frequencies for a clearly bounded archived sample."""
    valid = [
        row for row in rows
        if row.get("home_score") is not None and row.get("away_score") is not None
    ]
    count = len(valid)
    totals = [int(row["home_score"]) + int(row["away_score"]) for row in valid]
    home_goals = [int(row["home_score"]) for row in valid]
    away_goals = [int(row["away_score"]) for row in valid]
    over_counts = {
        "1_5": sum(total >= 2 for total in totals),
        "2_5": sum(total >= 3 for total in totals),
        "3_5": sum(total >= 4 for total in totals),
    }
    markets = {}
    for line, over_count in over_counts.items():
        under_count = count - over_count
        markets[line] = {
            "over": {"count": over_count, "percentage": _percentage(over_count, count)},
            "under": {"count": under_count, "percentage": _percentage(under_count, count)},
        }
    btts = sum(home > 0 and away > 0 for home, away in zip(home_goals, away_goals))
    distribution = {
        "0_1": sum(total <= 1 for total in totals),
        "2": sum(total == 2 for total in totals),
        "3": sum(total == 3 for total in totals),
        "4_plus": sum(total >= 4 for total in totals),
    }
    return {
        "sample_size": count,
        "average_total_goals": round(sum(totals) / count, 3) if count else None,
        "average_home_goals": round(sum(home_goals) / count, 3) if count else None,
        "average_away_goals": round(sum(away_goals) / count, 3) if count else None,
        "markets": markets,
        "both_teams_scored": {
            "count": btts,
            "percentage": _percentage(btts, count),
        },
        "total_goals_distribution": {
            key: {"count": value, "percentage": _percentage(value, count)}
            for key, value in distribution.items()
        },
        "home_team_goals_distribution": _goal_bucket_counts(home_goals, count),
        "away_team_goals_distribution": _goal_bucket_counts(away_goals, count),
    }


def _summarize_season_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptive season metrics; empty samples retain null rates."""
    valid = [row for row in rows if row.get("home_score") is not None and row.get("away_score") is not None]
    count = len(valid)
    home_goals = [int(row["home_score"]) for row in valid]
    away_goals = [int(row["away_score"]) for row in valid]
    totals = [home + away for home, away in zip(home_goals, away_goals)]
    home_wins = sum(home > away for home, away in zip(home_goals, away_goals))
    draws = sum(home == away for home, away in zip(home_goals, away_goals))
    away_wins = count - home_wins - draws
    over_1_5 = sum(total >= 2 for total in totals)
    over_2_5 = sum(total >= 3 for total in totals)
    over_3_5 = sum(total >= 4 for total in totals)
    btts = sum(home > 0 and away > 0 for home, away in zip(home_goals, away_goals))
    dates = [str(row["match_date"]) for row in valid if row.get("match_date")]
    return {
        "matches": count, "sample_start": min(dates) if dates else None,
        "sample_end": max(dates) if dates else None,
        "home_wins": home_wins, "draws": draws, "away_wins": away_wins,
        "home_win_percentage": _percentage(home_wins, count),
        "draw_percentage": _percentage(draws, count),
        "away_win_percentage": _percentage(away_wins, count),
        "average_home_goals": round(sum(home_goals) / count, 3) if count else None,
        "average_away_goals": round(sum(away_goals) / count, 3) if count else None,
        "average_total_goals": round(sum(totals) / count, 3) if count else None,
        "over_1_5": {"count": over_1_5, "percentage": _percentage(over_1_5, count)},
        "over_2_5": {"count": over_2_5, "percentage": _percentage(over_2_5, count)},
        "over_3_5": {"count": over_3_5, "percentage": _percentage(over_3_5, count)},
        "both_teams_scored": {"count": btts, "percentage": _percentage(btts, count)},
    }


@router.get("/season-comparison")
def archive_season_comparison(
    competition: str = Query(...),
    season: str = Query(..., min_length=4, max_length=4),
):
    """Compare one archived season across leagues and adjacent seasons in one league."""
    code = competition.strip().upper()
    selected_season = season.strip()
    if code not in COMPETITIONS:
        raise HTTPException(status_code=400, detail=f"Competición no admitida. Usa: {', '.join(COMPETITIONS)}.")
    if not selected_season.isdigit():
        raise HTTPException(status_code=400, detail="La temporada debe usar el código de cuatro dígitos, por ejemplo 2526.")

    start_short = int(selected_season[:2])
    start_year = 2000 + start_short if start_short < 90 else 1900 + start_short
    season_codes = [
        f"{(start_year + offset) % 100:02d}{(start_year + offset + 1) % 100:02d}"
        for offset in (-1, 0, 1)
    ]
    client = _client_or_503()
    try:
        def read_sample(competition_code: str, season_code: str) -> list[dict[str, Any]]:
            result = client.table("football_match_archive").select(
                "match_date,home_score,away_score"
            ).eq("competition_code", competition_code).eq(
                "season", season_code
            ).order("match_date").limit(1000).execute()
            return [
                row for row in (result.data or [])
                if row.get("home_score") is not None and row.get("away_score") is not None
            ]

        cross_competition = []
        for competition_code, config in COMPETITIONS.items():
            rows = read_sample(competition_code, selected_season)
            cross_competition.append({
                "competition": competition_code, "competition_name": config["name"],
                "season": selected_season, **_summarize_season_results(rows),
            })
        season_trend = []
        for season_code in season_codes:
            rows = read_sample(code, season_code)
            season_trend.append({
                "competition": code, "competition_name": COMPETITIONS[code]["name"],
                "season": season_code, **_summarize_season_results(rows),
            })
    except Exception as exc:
        logger.exception("Could not compare archived football seasons and competitions")
        raise HTTPException(status_code=503, detail="No se pudieron comparar las temporadas del archivo propio.") from exc

    return {
        "success": True, "selected_competition": code,
        "selected_competition_name": COMPETITIONS[code]["name"],
        "selected_season": selected_season,
        "cross_competition": cross_competition, "season_trend": season_trend,
        "source": "Sports Predictor · Supabase archive", "provider_calls": 0,
        "model_changed": False,
        "interpretation": "Comparaciones descriptivas de resultados históricos completos; las frecuencias no son probabilidades futuras ni recomendaciones de apuesta.",
    }


@router.get("/market-patterns")
def archive_market_patterns(
    competition: str = Query(...),
    home_team: str = Query(..., min_length=2, max_length=100),
    away_team: str = Query(..., min_length=2, max_length=100),
    kickoff_at: str | None = None,
):
    """Compare recent league goal-market frequencies with each team's own recent sample."""
    code = competition.strip().upper()
    if code not in COMPETITIONS:
        raise HTTPException(status_code=400, detail=f"Competición no admitida. Usa: {', '.join(COMPETITIONS)}.")
    if not kickoff_at:
        raise HTTPException(status_code=400, detail="kickoff_at es obligatorio para excluir resultados posteriores al partido.")
    try:
        cutoff = datetime.fromisoformat(kickoff_at.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="kickoff_at no es una fecha ISO 8601 válida.") from exc

    client = _client_or_503()
    resolved = {}
    for side, name in (("home", home_team), ("away", away_team)):
        key, resolution = _resolve_team_identity(client, code, name)
        if not key:
            raise HTTPException(status_code=400, detail=f"No se pudo resolver la identidad de {name}.")
        resolved[side] = {"name": name, "key": key, "resolution": resolution}
    if resolved["home"]["key"] == resolved["away"]["key"]:
        raise HTTPException(status_code=400, detail="Los equipos deben tener identidades distintas en el archivo.")

    try:
        league_query = client.table("football_match_archive").select("*").eq(
            "competition_code", code
        ).lt("match_date", cutoff).order("match_date", desc=True).limit(1000)
        league_rows = league_query.execute().data or []
        teams = {}
        for side, identity in resolved.items():
            query = client.table("football_match_archive").select("*").eq(
                "competition_code", code
            ).or_(
                f"home_team_key.eq.{identity['key']},away_team_key.eq.{identity['key']}"
            ).lt("match_date", cutoff).order("match_date", desc=True).limit(100)
            rows = query.execute().data or []
            oriented = [
                _team_form_match(row, identity["key"])
                for row in rows
                if identity["key"] in {row.get("home_team_key"), row.get("away_team_key")}
                and row.get("home_score") is not None
                and row.get("away_score") is not None
                and str(row.get("match_date") or "") < cutoff
            ]
            teams[side] = {
                **identity,
                "sample_size": len(oriented),
                "sample_limit": 100,
                "windows": _summarize_team_form(oriented),
                "venue_windows": {"home": _summarize_venue_windows(oriented, "home"), "away": _summarize_venue_windows(oriented, "away")},
                "sample_start": min((item.get("date") for item in oriented if item.get("date")), default=None),
                "sample_end": max((item.get("date") for item in oriented if item.get("date")), default=None),
            }
    except Exception as exc:
        logger.exception("Could not query historical football market patterns")
        raise HTTPException(status_code=503, detail="No se pudieron consultar los patrones del archivo propio.") from exc

    league_rows = [
        row for row in league_rows
        if row.get("home_score") is not None and row.get("away_score") is not None
        and str(row.get("match_date") or "") < cutoff
    ]
    dates = [str(row["match_date"]) for row in league_rows if row.get("match_date")]
    home_venue_matches = [_team_form_match(row, row["home_team_key"]) for row in league_rows if row.get("home_team_key") and row.get("home_score") is not None and row.get("away_score") is not None]
    away_venue_matches = [_team_form_match(row, row["away_team_key"]) for row in league_rows if row.get("away_team_key") and row.get("home_score") is not None and row.get("away_score") is not None]
    home_win_rate = _percentage(sum(item["result"] == "W" for item in home_venue_matches), len(home_venue_matches))
    away_win_rate = _percentage(sum(item["result"] == "W" for item in away_venue_matches), len(away_venue_matches))
    return {
        "success": True,
        "provider": "Sports Predictor · Supabase archive",
        "source": SOURCE_NAME,
        "competition": code,
        "competition_name": COMPETITIONS[code]["name"],
        "history_scope": "Muestra de hasta 1.000 partidos finalizados más recientes de esta competición; para cada equipo se consultan hasta 100 partidos previos y se calculan ventanas generales y específicas de localía de 5, 10 y 15 partidos.",
        "cutoff_date_exclusive": cutoff,
        "competition_sample": {
            **_summarize_market_sample(league_rows),
            "sample_start": min(dates) if dates else None,
            "sample_end": max(dates) if dates else None,
            "sample_limit": 1000,
            "limit_reached": len(league_rows) == 1000,
        },
        "competition_venue_advantage": {
            "home_teams": _summarize_venue_sample(home_venue_matches),
            "away_teams": _summarize_venue_sample(away_venue_matches),
            "home_win_rate": home_win_rate,
            "draw_rate": _percentage(sum(item["result"] == "D" for item in home_venue_matches), len(home_venue_matches)),
            "away_win_rate": away_win_rate,
            "home_win_rate_minus_away_win_rate": round(home_win_rate - away_win_rate, 2) if home_win_rate is not None and away_win_rate is not None else None,
        },
        "teams": teams,
        "provider_calls": 0,
        "model_changed": False,
        "interpretation": "Frecuencias históricas descriptivas; no son probabilidades futuras ni recomendaciones de apuesta.",
    }


@router.get("/team-form")
def archive_team_recent_form(
    competition: str = Query(...),
    home_team: str = Query(..., min_length=2, max_length=100),
    away_team: str = Query(..., min_length=2, max_length=100),
    kickoff_at: str | None = None,
):
    """Compare both teams' last 5/10/15 completed league matches from our archive."""
    code = competition.strip().upper()
    if code not in COMPETITIONS:
        raise HTTPException(status_code=400, detail=f"Competición no admitida. Usa: {', '.join(COMPETITIONS)}.")
    if not kickoff_at:
        raise HTTPException(status_code=400, detail="kickoff_at es obligatorio para evitar incluir resultados posteriores al partido.")
    try:
        cutoff = datetime.fromisoformat(kickoff_at.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="kickoff_at no es una fecha ISO 8601 válida.") from exc

    client = _client_or_503()
    resolved = {}
    for side, name in (("home", home_team), ("away", away_team)):
        key, resolution = _resolve_team_identity(client, code, name)
        if not key:
            raise HTTPException(status_code=400, detail=f"No se pudo resolver la identidad de {name}.")
        resolved[side] = {"name": name, "key": key, "resolution": resolution}
    if resolved["home"]["key"] == resolved["away"]["key"]:
        raise HTTPException(status_code=400, detail="Los equipos deben tener identidades distintas en el archivo.")

    teams = {}
    try:
        for side, identity in resolved.items():
            query = client.table("football_match_archive").select("*").eq(
                "competition_code", code
            ).or_(
                f"home_team_key.eq.{identity['key']},away_team_key.eq.{identity['key']}"
            )
            # The cutoff is applied in the database before LIMIT so future fixtures
            # cannot displace valid historical matches from the requested sample.
            if cutoff:
                query = query.lt("match_date", cutoff)
            rows = query.order("match_date", desc=True).limit(15).execute().data or []
            oriented = [
                _team_form_match(row, identity["key"])
                for row in rows
                if identity["key"] in {row.get("home_team_key"), row.get("away_team_key")}
                and row.get("home_score") is not None
                and row.get("away_score") is not None
            ]
            teams[side] = {
                **identity,
                "sample_size": len(oriented),
                "windows": _summarize_team_form(oriented),
                "recent_matches": oriented,
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not query recent football team form")
        raise HTTPException(status_code=503, detail="No se pudo consultar la forma reciente del archivo propio.") from exc

    return {
        "success": True,
        "provider": "Sports Predictor · Supabase archive",
        "source": SOURCE_NAME,
        "competition": code,
        "competition_name": COMPETITIONS[code]["name"],
        "history_scope": "Solo partidos finalizados de esta competición almacenados en el archivo propio.",
        "cutoff_date_exclusive": cutoff,
        "teams": teams,
        "windows": [5, 10, 15],
        "provider_calls": 0,
        "model_changed": False,
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


@router.get("/research-backtest")
def archive_research_backtest(
    competition: str = Query(..., min_length=2, max_length=8),
    limit: int = Query(500, ge=100, le=500),
):
    """Run read-only chronological model research using only our owned archive."""
    code = competition.strip().upper()
    if code not in COMPETITIONS:
        raise HTTPException(status_code=400, detail=f"Competición no admitida. Usa: {', '.join(COMPETITIONS)}.")

    try:
        client = _client_or_503()
        rows = []
        page_size = 1000
        max_history_rows = 12000
        for offset in range(0, max_history_rows, page_size):
            query = client.table("football_match_archive").select(
                "source_key,match_date,season,home_team,away_team,home_score,away_score"
            ).eq("competition_code", code).order("match_date", desc=True)
            page = query.range(offset, offset + page_size - 1).execute().data or []
            rows.extend(page)
            if len(page) < page_size:
                break
    except Exception as exc:
        logger.exception("Could not load archive rows for football research backtest")
        raise HTTPException(status_code=503, detail="No se pudo cargar el historial propio para investigación.") from exc

    history_truncated = len(rows) >= max_history_rows
    # Use the full retrieved archive as training history and only the latest
    # requested number of eligible fixtures as evaluation targets. Archive dates
    # have no kickoff times, so all matches on each calendar day share midnight UTC.
    matches = []
    for row in reversed(rows):
        home_score, away_score = row.get("home_score"), row.get("away_score")
        match_date = str(row.get("match_date") or "")
        home, away = row.get("home_team"), row.get("away_team")
        if (not match_date or not home or not away
                or not isinstance(home_score, int) or isinstance(home_score, bool) or home_score < 0
                or not isinstance(away_score, int) or isinstance(away_score, bool) or away_score < 0):
            continue
        matches.append({
            "id": row.get("source_key") or f"{code}-{match_date}-{len(matches)}",
            "season": row.get("season"),
            "status": "FINISHED",
            "utcDate": f"{match_date}T00:00:00Z",
            "homeTeam": {"name": str(home)},
            "awayTeam": {"name": str(away)},
            "score": {"fullTime": {"home": home_score, "away": away_score}},
        })

    try:
        evaluation = run_chronological_backtest(matches, target_limit=limit)
        validation = build_candidate_validation(evaluation)
    except Exception as exc:
        logger.exception("Football archive chronological research evaluation failed")
        raise HTTPException(status_code=500, detail="No se pudo completar la evaluación cronológica del archivo.") from exc

    # Keep the API response compact; the summary metrics and diagnostics are
    # sufficient for the research panel. Per-match payloads are not persisted.
    evaluation["per_match_count"] = len(evaluation.get("per_match") or [])
    evaluation["advanced_goals_shadow_per_match_count"] = len(
        evaluation.get("advanced_goals_shadow_per_match") or []
    )
    evaluation.pop("per_match", None)
    evaluation.pop("advanced_goals_shadow_per_match", None)
    return {
        "success": True,
        "provider": "Sports Predictor · Supabase archive",
        "source": SOURCE_NAME,
        "competition": code,
        "competition_name": COMPETITIONS[code]["name"],
        "sample_limit": limit,
        "input_sample_size": len(matches),
        "target_sample_size": evaluation.get("target_sample_size", 0),
        "history_truncated": history_truncated,
        "cutoff_policy": "Partidos del mismo día calendario quedan excluidos del entrenamiento; solo se usan fechas estrictamente anteriores porque el archivo no conserva hora de inicio.",
        "evaluation": evaluation,
        "validation": validation,
        "provider_calls": 0,
        "model_changed": False,
        "snapshots_written": 0,
    }
