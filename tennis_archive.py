"""Persistent ATP/WTA results archive sourced from Valuebetennis open CSVs.

Valuebetennis publishes exact UTC match dates, surfaces, tournament categories,
stable source match IDs, player IDs, and final scores under CC BY 4.0.
This archive is deliberately separate from the legacy Sackmann-derived files:
it preserves source provenance and does not change or activate any prediction
model. The source attribution is stored on every imported row.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any

from repository import get_supabase_client
from tennis_external_source import (
    CSV_URL_TEMPLATE,
    SOURCE_ATTRIBUTION,
    SOURCE_LICENSE,
    _match_day,
    load_external_year,
)

logger = logging.getLogger(__name__)
TABLE = "tennis_match_archive"
UPSERT_BATCH_SIZE = 500
MIN_YEAR = 2021
SUPPORTED_LEAGUES = {"ATP", "WTA"}
ELIGIBLE_CATEGORIES = {"main tour", "masters", "grand chelem", "grand slam"}


class TennisArchiveImportError(RuntimeError):
    """Raised when source rows cannot be safely persisted."""


def _optional_nonnegative_int(value: Any) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _utc_timestamp(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw or "T" not in raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def build_match_payload(row: dict[str, Any], imported_at: str) -> dict[str, Any] | None:
    """Validate and normalize one source row; invalid rows are never guessed."""
    source_match_id = str(row.get("match_id") or "").strip()
    league = str(row.get("genre") or "").strip().upper()
    player1_id = str(row.get("joueur1_id") or "").strip()
    player2_id = str(row.get("joueur2_id") or "").strip()
    player1_name = str(row.get("joueur1") or "").strip()
    player2_name = str(row.get("joueur2") or "").strip()
    winner_id = str(row.get("vainqueur_id") or "").strip()
    match_date = _match_day(str(row.get("date") or ""))

    if (
        not source_match_id
        or league not in SUPPORTED_LEAGUES
        or match_date is None
        or not player1_id
        or not player2_id
        or player1_id == player2_id
        or not player1_name
        or not player2_name
        or player1_name.casefold() == player2_name.casefold()
        or winner_id not in {player1_id, player2_id}
    ):
        return None

    tournament = str(row.get("tournoi") or "").strip()
    category = str(row.get("categorie") or "").strip() or "Unknown"
    if not tournament or category.casefold() not in ELIGIBLE_CATEGORIES:
        return None

    surface_detail = str(row.get("surface") or "").strip() or None
    surface_key = (surface_detail or "").casefold().replace(".", "").strip()
    if surface_key in {"hard", "indoor hard", "i hard", "ihard"}:
        surface = "Hard"
    elif surface_key == "clay":
        surface = "Clay"
    elif surface_key == "grass":
        surface = "Grass"
    elif surface_key == "carpet":
        surface = "Carpet"
    else:
        surface = "Other" if surface_detail else None

    return {
        "source_match_id": source_match_id,
        "source": "Valuebetennis",
        "source_url": CSV_URL_TEMPLATE.format(year=match_date.year),
        "source_license": SOURCE_LICENSE,
        "source_attribution": SOURCE_ATTRIBUTION,
        "league": league,
        "match_date": match_date.isoformat(),
        "match_datetime_utc": _utc_timestamp(row.get("date")),
        "tournament": tournament,
        "tournament_id": str(row.get("tournoi_id") or "").strip() or None,
        "category": category,
        "surface": surface,
        "surface_detail": surface_detail,
        "round_code": _optional_nonnegative_int(row.get("tour")),
        "player1_id": player1_id,
        "player1_name": player1_name,
        "player1_name_key": normalize_player_name(player1_name),
        "player2_id": player2_id,
        "player2_name": player2_name,
        "player2_name_key": normalize_player_name(player2_name),
        "winner_id": winner_id,
        "score": str(row.get("score") or "").strip()[:100] or None,
        "duration_minutes": _optional_nonnegative_int(row.get("duree_min")),
        "imported_at": imported_at,
    }


def parse_year_rows(
    rows: tuple[dict[str, str], ...] | list[dict[str, str]],
    year: int,
    imported_at: str,
) -> dict[str, Any]:
    """Build a unique batch; conflicting duplicate source IDs fail closed."""
    unique: dict[str, dict[str, Any]] = {}
    rejected = 0
    excluded_category = 0
    duplicates = 0
    for row in rows:
        category = str(row.get("categorie") or "").strip().casefold()
        if category not in ELIGIBLE_CATEGORIES:
            excluded_category += 1
            continue
        payload = build_match_payload(row, imported_at)
        if payload is None:
            rejected += 1
            continue
        if date.fromisoformat(payload["match_date"]).year != year:
            rejected += 1
            continue
        key = f"{payload['league']}:{payload['source_match_id']}"
        existing = unique.get(key)
        if existing is not None:
            comparable_existing = {k: v for k, v in existing.items() if k != "imported_at"}
            comparable_payload = {k: v for k, v in payload.items() if k != "imported_at"}
            if comparable_existing != comparable_payload:
                raise TennisArchiveImportError(
                    f"El source_match_id {key} aparece con datos contradictorios en {year}."
                )
            duplicates += 1
            continue
        unique[key] = payload
    return {
        "rows": list(unique.values()),
        "rows_seen": len(rows),
        "rows_rejected": rejected,
        "rows_excluded_category": excluded_category,
        "duplicate_rows": duplicates,
    }


def sync_tennis_archive(
    start_year: int = MIN_YEAR,
    end_year: int | None = None,
) -> dict[str, Any]:
    """Idempotently upsert the requested annual files into Supabase."""
    current_year = datetime.now(timezone.utc).year
    end = int(end_year) if end_year is not None else current_year
    start = int(start_year)
    if start < MIN_YEAR or end < start or end > current_year:
        raise ValueError(f"El rango debe estar entre {MIN_YEAR} y {current_year}.")

    client = get_supabase_client()
    imported_at = datetime.now(timezone.utc).isoformat()
    totals = {
        "years_requested": end - start + 1,
        "years_loaded": 0,
        "rows_seen": 0,
        "valid_matches": 0,
        "rows_rejected": 0,
        "rows_excluded_category": 0,
        "duplicate_rows": 0,
        "upserted_rows": 0,
        "failed_years": 0,
    }
    by_year: list[dict[str, Any]] = []
    errors: list[str] = []

    for year in range(start, end + 1):
        result: dict[str, Any] = {"year": year, "status": "pending", "valid_matches": 0}
        try:
            source_rows = load_external_year(year)
            parsed = parse_year_rows(source_rows, year, imported_at)
            payloads = parsed["rows"]
            result.update({
                "status": "loaded",
                "valid_matches": len(payloads),
                "rows_seen": parsed["rows_seen"],
                "rows_rejected": parsed["rows_rejected"],
                "rows_excluded_category": parsed["rows_excluded_category"],
                "duplicate_rows": parsed["duplicate_rows"],
            })
            totals["years_loaded"] += 1
            totals["rows_seen"] += parsed["rows_seen"]
            totals["valid_matches"] += len(payloads)
            totals["rows_rejected"] += parsed["rows_rejected"]
            totals["rows_excluded_category"] += parsed["rows_excluded_category"]
            totals["duplicate_rows"] += parsed["duplicate_rows"]

            for offset in range(0, len(payloads), UPSERT_BATCH_SIZE):
                batch = payloads[offset:offset + UPSERT_BATCH_SIZE]
                if batch:
                    client.table(TABLE).upsert(
                        batch, on_conflict="league,source_match_id"
                    ).execute()
                    totals["upserted_rows"] += len(batch)
            result["status"] = "imported"
        except Exception as exc:
            totals["failed_years"] += 1
            result["status"] = "failed"
            result["error"] = str(exc)[:240]
            errors.append(f"{year}: {str(exc)[:200]}")
            logger.exception("Tennis archive import failed for %s", year)
        by_year.append(result)

    return {
        "success": totals["failed_years"] == 0,
        "source": "Valuebetennis",
        "source_license": SOURCE_LICENSE,
        "source_attribution": SOURCE_ATTRIBUTION,
        "start_year": start,
        "end_year": end,
        **totals,
        "by_year": by_year,
        "errors": errors[:20],
    }


def normalize_player_name(value: Any) -> str:
    """Normalize names conservatively for exact-key lookup, never fuzzy-match."""
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_name = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_name = ascii_name.casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_name).split())


def get_player_archive_profile(
    player_name: str,
    league: str,
    cutoff_date: date,
    lookback_days: int,
    surface: str | None = None,
) -> dict[str, Any] | None:
    """Read exact-date player form from the persisted, source-attributed archive.

    Returns None when the archive is not yet installed/populated so callers
    can preserve the legacy read path. Ambiguous name-to-ID matches are flagged
    and are never combined into one player's profile.
    """
    target = normalize_player_name(player_name)
    selected_league = str(league or "").strip().upper()
    if not target or selected_league not in SUPPORTED_LEAGUES:
        return None

    client = get_supabase_client()
    start = cutoff_date - timedelta(days=int(lookback_days))
    columns = (
        "source_match_id,match_date,match_datetime_utc,tournament,category,surface,"
        "round_code,player1_id,player1_name,player1_name_key,player2_id,"
        "player2_name,player2_name_key,winner_id,score"
    )
    first = (
        client.table(TABLE).select(columns)
        .eq("league", selected_league)
        .eq("player1_name_key", target)
        .gte("match_date", start.isoformat())
        .lt("match_date", cutoff_date.isoformat())
        .order("match_date", desc=False).limit(1000).execute()
    ).data or []
    second = (
        client.table(TABLE).select(columns)
        .eq("league", selected_league)
        .eq("player2_name_key", target)
        .gte("match_date", start.isoformat())
        .lt("match_date", cutoff_date.isoformat())
        .order("match_date", desc=False).limit(1000).execute()
    ).data or []

    unique: dict[str, dict[str, Any]] = {}
    for row in first + second:
        unique[str(row.get("source_match_id") or "")] = row
    rows = list(unique.values())
    rows = [
        row for row in rows
        if str(row.get("category") or "").strip().casefold() in ELIGIBLE_CATEGORIES
    ]
    if not rows:
        return None

    player_ids = set()
    for row in rows:
        if row.get("player1_name_key") == target:
            player_ids.add(str(row.get("player1_id") or ""))
        if row.get("player2_name_key") == target:
            player_ids.add(str(row.get("player2_id") or ""))
    player_ids.discard("")
    if len(player_ids) != 1:
        return {"identity_ambiguous": True}

    player_id = next(iter(player_ids))
    rows.sort(key=lambda row: (
        str(row.get("match_date") or ""),
        str(row.get("match_datetime_utc") or ""),
        str(row.get("source_match_id") or ""),
    ))
    matches = []
    for row in rows:
        side = (
            "player1" if str(row.get("player1_id") or "") == player_id
            else "player2" if str(row.get("player2_id") or "") == player_id
            else None
        )
        if side is None:
            continue
        opponent_side = "player2" if side == "player1" else "player1"
        winner = str(row.get("winner_id") or "")
        is_walkover = bool(re.search(
            r"\bW\s*/?\s*O\b|\bWALKOVER\b",
            str(row.get("score") or ""),
            re.IGNORECASE,
        ))
        matches.append({
            "date": str(row.get("match_date")),
            "date_precision": "exact_match_date",
            "is_walkover": is_walkover,
            "tournament": row.get("tournament"),
            "category": row.get("category"),
            "opponent": str(row.get(f"{opponent_side}_name") or "Desconocido"),
            "result": "W" if winner == player_id else "L",
            "score": str(row.get("score") or "").strip() or None,
            "surface": row.get("surface"),
            "round": str(row.get("round_code")) if row.get("round_code") is not None else None,
        })

    if not matches:
        return None

    def summarize(sample):
        wins = sum(item["result"] == "W" for item in sample)
        losses = len(sample) - wins
        return {
            "matches": len(sample),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(sample), 4) if sample else None,
        }

    last_5 = matches[-5:]
    last_10 = matches[-10:]
    last_played = date.fromisoformat(matches[-1]["date"])
    selected = [item for item in matches if not surface or item["surface"] == surface]
    surface_wins = sum(item["result"] == "W" for item in selected)

    latest_result = (
        client.table(TABLE).select("match_date")
        .eq("league", selected_league)
        .lt("match_date", cutoff_date.isoformat())
        .order("match_date", desc=True).limit(1).execute()
    ).data or []
    latest_source_date = (
        date.fromisoformat(str(latest_result[0]["match_date"])[:10])
        if latest_result else None
    )
    source_age = (cutoff_date - latest_source_date).days if latest_source_date else None
    freshness = (
        "unknown" if source_age is None
        else "current" if source_age <= 45
        else "delayed" if source_age <= 90
        else "stale"
    )

    return {
        "success": True,
        "league": selected_league,
        "player_name": player_name,
        "cutoff_date_exclusive": cutoff_date.isoformat(),
        "lookback_days": int(lookback_days),
        "matches_in_window": len(matches),
        "wins_in_window": sum(item["result"] == "W" for item in matches),
        "losses_in_window": sum(item["result"] == "L" for item in matches),
        "win_rate": round(
            sum(item["result"] == "W" for item in matches) / len(matches), 4
        ),
        "last_5": summarize(last_5),
        "last_10": summarize(last_10),
        "recent_matches": list(reversed(matches[-10:])),
        "surface_window": {
            "matches": len(selected),
            "wins": surface_wins,
            "losses": len(selected) - surface_wins,
            "win_rate": round(surface_wins / len(selected), 4) if selected else None,
        },
        "ranking_latest_in_window": None,
        "days_since_last_match": (cutoff_date - last_played).days,
        "workload_matches_last_7_days": sum(
            date.fromisoformat(item["date"]) >= cutoff_date - timedelta(days=7)
            for item in matches
        ),
        "workload_matches_last_14_days": sum(
            date.fromisoformat(item["date"]) >= cutoff_date - timedelta(days=14)
            for item in matches
        ),
        "service_return_stats_last_10_matches": {
            "matches_with_service_stats": 0,
            "aces_total": None,
            "double_faults_total": None,
            "aces_per_match": None,
            "double_faults_per_match": None,
            "first_serve_in_pct": None,
            "first_serve_points_won_pct": None,
            "second_serve_points_won_pct": None,
            "break_points_saved_pct": None,
        },
        "data_quality": {
            "annual_files_available": [],
            "matches_found": len(matches),
            "matches_with_service_stats": 0,
            "latest_match_date_in_source": latest_source_date.isoformat() if latest_source_date else None,
            "source_data_age_days": source_age,
            "source_freshness_status": freshness,
            "source_freshness_thresholds_days": {"current_max": 45, "delayed_max": 90},
            "source": "Valuebetennis ATP/WTA historical match CSV",
            "source_url": "https://www.valuebetennis.com/donnees.htm",
            "source_license": SOURCE_LICENSE,
            "source_attribution": SOURCE_ATTRIBUTION,
            "warning": (
                "Perfil actualizado con fechas exactas y superficie desde Valuebetennis. "
                "Esta fuente no publica estadísticas de saque; no se estiman ni se rellenan."
            ),
        },
    }
