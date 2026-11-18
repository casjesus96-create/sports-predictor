"""Persistent ATP/WTA results archive sourced from Valuebetennis open CSVs.

Valuebetennis publishes exact UTC match dates, surfaces, tournament categories,
stable source match IDs, player IDs, and final scores under CC BY 4.0.
This archive is deliberately separate from the legacy Sackmann-derived files:
it preserves source provenance and does not change or activate any prediction
model. The source attribution is stored on every imported row.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
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
    if not tournament:
        return None

    surface = str(row.get("surface") or "").strip().title() or None
    if surface not in {None, "Hard", "Clay", "Grass", "Carpet"}:
        surface = "Other"

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
        "category": str(row.get("categorie") or "").strip() or "Unknown",
        "surface": surface,
        "round_code": _optional_nonnegative_int(row.get("tour")),
        "player1_id": player1_id,
        "player1_name": player1_name,
        "player2_id": player2_id,
        "player2_name": player2_name,
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
    duplicates = 0
    for row in rows:
        payload = build_match_payload(row, imported_at)
        if payload is None:
            rejected += 1
            continue
        if date.fromisoformat(payload["match_date"]).year != year:
            rejected += 1
            continue
        key = payload["source_match_id"]
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
                "duplicate_rows": parsed["duplicate_rows"],
            })
            totals["years_loaded"] += 1
            totals["rows_seen"] += parsed["rows_seen"]
            totals["valid_matches"] += len(payloads)
            totals["rows_rejected"] += parsed["rows_rejected"]
            totals["duplicate_rows"] += parsed["duplicate_rows"]

            for offset in range(0, len(payloads), UPSERT_BATCH_SIZE):
                batch = payloads[offset:offset + UPSERT_BATCH_SIZE]
                if batch:
                    client.table(TABLE).upsert(
                        batch, on_conflict="source_match_id"
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
