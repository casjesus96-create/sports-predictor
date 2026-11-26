"""Persistent ATP/WTA results archive sourced from Valuebetennis open CSVs.

Valuebetennis publishes exact UTC match dates, surfaces, tournament categories,
stable source match IDs, player IDs, and final scores under CC BY 4.0.
This archive is deliberately separate from the legacy Sackmann-derived files:
it preserves source provenance and does not change or activate any prediction
model. The source attribution is stored on every imported row.
"""
from __future__ import annotations

import hashlib
import json
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
ELIGIBLE_CATEGORIES = {"main tour", "masters", "grand chelem", "grand slam", "challenger"}


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


def _stable_source_match_id(
    row: dict[str, Any], league: str, match_date: date
) -> tuple[str, bool]:
    """Use the publisher ID, or a deterministic fingerprint of match facts.

    The fallback is explicitly namespaced so it can never be mistaken for a
    publisher-issued ID. It uses both player IDs, event, exact date/time,
    round, score and winner; it does not use row position or import time.
    """
    supplied = str(row.get("match_id") or "").strip()
    if supplied:
        return supplied, False

    identity = {
        "league": league,
        "match_date": match_date.isoformat(),
        "match_datetime_utc": _utc_timestamp(row.get("date")) or "",
        "tournament_id": str(row.get("tournoi_id") or "").strip(),
        "tournament": " ".join(str(row.get("tournoi") or "").casefold().split()),
        "round": str(row.get("tour") or "").strip(),
        "players": sorted((
            str(row.get("joueur1_id") or "").strip(),
            str(row.get("joueur2_id") or "").strip(),
        )),
        "winner_id": str(row.get("vainqueur_id") or "").strip(),
        "score": " ".join(str(row.get("score") or "").split()),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"derived:{digest}", True



def _normalize_surface(surface_detail: str | None) -> str | None:
    """Map source surface labels to canonical groups without altering raw labels.

    Valuebetennis uses English and French labels. Some CSV exports contain
    the common UTF-8-as-Latin-1 form of "é" (rendered as "Ã©"); normalize that
    known sequence only for classification and preserve surface_detail verbatim.
    """
    if not surface_detail:
        return None

    raw = surface_detail.casefold().strip().replace("ã©", "e")
    decomposed = unicodedata.normalize("NFKD", raw)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    key = " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())

    surface_groups = {
        "hard": "Hard",
        "indoor hard": "Hard",
        "i hard": "Hard",
        "ihard": "Hard",
        "dur": "Hard",
        "dur interieur": "Hard",
        "clay": "Clay",
        "terre battue": "Clay",
        "grass": "Grass",
        "gazon": "Grass",
        "carpet": "Carpet",
        "moquette interieur": "Carpet",
    }
    return surface_groups.get(key, "Other")

def build_match_payload(row: dict[str, Any], imported_at: str) -> dict[str, Any] | None:
    """Validate and normalize one source row; invalid rows are never guessed."""
    league = str(row.get("genre") or "").strip().upper()
    player1_id = str(row.get("joueur1_id") or "").strip()
    player2_id = str(row.get("joueur2_id") or "").strip()
    player1_name = str(row.get("joueur1") or "").strip()
    player2_name = str(row.get("joueur2") or "").strip()
    winner_id = str(row.get("vainqueur_id") or "").strip()
    match_date = _match_day(str(row.get("date") or ""))

    if (
        league not in SUPPORTED_LEAGUES
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

    source_match_id, _derived_id = _stable_source_match_id(row, league, match_date)
    surface_detail = str(row.get("surface") or "").strip() or None
    surface = _normalize_surface(surface_detail)

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


def _normalized_category(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def _rejection_reason(row: dict[str, Any], year: int) -> str:
    """Return the first failed validation so source drift is diagnosable."""
    if str(row.get("genre") or "").strip().upper() not in SUPPORTED_LEAGUES:
        return "unsupported_or_missing_league"
    played_on = _match_day(str(row.get("date") or ""))
    if played_on is None:
        return "invalid_or_missing_date"
    if played_on.year != year:
        return "date_outside_requested_year"
    p1 = str(row.get("joueur1_id") or "").strip()
    p2 = str(row.get("joueur2_id") or "").strip()
    if not p1 or not p2:
        return "missing_player_id"
    if p1 == p2:
        return "same_player_id"
    n1 = str(row.get("joueur1") or "").strip()
    n2 = str(row.get("joueur2") or "").strip()
    if not n1 or not n2:
        return "missing_player_name"
    if n1.casefold() == n2.casefold():
        return "same_player_name"
    if str(row.get("vainqueur_id") or "").strip() not in {p1, p2}:
        return "winner_not_a_participant"
    if not str(row.get("tournoi") or "").strip():
        return "missing_tournament"
    return "payload_validation_failed"


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
    category_counts: dict[str, int] = {}
    rejection_reasons: dict[str, int] = {}
    league_counts = {
        league: {
            "source_rows": 0,
            "eligible_matches": 0,
            "rows_rejected": 0,
            "rows_excluded_category": 0,
            "category_counts": {},
        }
        for league in sorted(SUPPORTED_LEAGUES)
    }
    for row in rows:
        league = str(row.get("genre") or "").strip().upper()
        if league in league_counts:
            league_counts[league]["source_rows"] += 1
        category_raw = str(row.get("categorie") or "").strip()
        category = _normalized_category(category_raw)
        category_counts[category or "<blank>"] = category_counts.get(category or "<blank>", 0) + 1
        if league in league_counts:
            league_categories = league_counts[league]["category_counts"]
            league_categories[category or "<blank>"] = league_categories.get(category or "<blank>", 0) + 1
        if category not in ELIGIBLE_CATEGORIES:
            excluded_category += 1
            if league in league_counts:
                league_counts[league]["rows_excluded_category"] += 1
            continue
        payload = build_match_payload(row, imported_at)
        if payload is None:
            rejected += 1
            if league in league_counts:
                league_counts[league]["rows_rejected"] += 1
            reason = _rejection_reason(row, year)
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
            continue
        if date.fromisoformat(payload["match_date"]).year != year:
            rejected += 1
            league_counts[league]["rows_rejected"] += 1
            rejection_reasons["date_outside_requested_year"] = rejection_reasons.get("date_outside_requested_year", 0) + 1
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
    for payload in unique.values():
        league_counts[payload["league"]]["eligible_matches"] += 1
    return {
        "rows": list(unique.values()),
        "league_counts": league_counts,
        "rows_seen": len(rows),
        "rows_rejected": rejected,
        "rows_excluded_category": excluded_category,
        "duplicate_rows": duplicates,
        "derived_match_ids": sum(
            str(item.get("source_match_id") or "").startswith("derived:")
            for item in unique.values()
        ),
        "category_counts": dict(sorted(category_counts.items())),
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
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
        "derived_match_ids": 0,
        "rows_rejected": 0,
        "rows_excluded_category": 0,
        "duplicate_rows": 0,
        "upserted_rows": 0,
        "failed_years": 0,
        "by_league": {
            league: {
                "source_rows": 0,
                "eligible_matches": 0,
                "rows_rejected": 0,
                "rows_excluded_category": 0,
                "category_counts": {},
                "upserted_rows": 0,
            }
            for league in sorted(SUPPORTED_LEAGUES)
        },
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
                "derived_match_ids": parsed["derived_match_ids"],
                "category_counts": parsed["category_counts"],
                "rejection_reasons": parsed["rejection_reasons"],
                "leagues": {
                    league: {**counts, "upserted_rows": 0}
                    for league, counts in parsed["league_counts"].items()
                },
            })
            totals["years_loaded"] += 1
            totals["rows_seen"] += parsed["rows_seen"]
            totals["valid_matches"] += len(payloads)
            totals["derived_match_ids"] += parsed["derived_match_ids"]
            totals["rows_rejected"] += parsed["rows_rejected"]
            totals["rows_excluded_category"] += parsed["rows_excluded_category"]
            totals["duplicate_rows"] += parsed["duplicate_rows"]
            for league, counts in parsed["league_counts"].items():
                for metric in ("source_rows", "eligible_matches", "rows_rejected", "rows_excluded_category"):
                    totals["by_league"][league][metric] += counts[metric]
                for category, count in counts["category_counts"].items():
                    aggregate = totals["by_league"][league]["category_counts"]
                    aggregate[category] = aggregate.get(category, 0) + count

            for league in sorted(SUPPORTED_LEAGUES):
                league_payloads = [item for item in payloads if item["league"] == league]
                for offset in range(0, len(league_payloads), UPSERT_BATCH_SIZE):
                    batch = league_payloads[offset:offset + UPSERT_BATCH_SIZE]
                    if batch:
                        client.table(TABLE).upsert(
                            batch, on_conflict="league,source_match_id"
                        ).execute()
                        totals["upserted_rows"] += len(batch)
                        totals["by_league"][league]["upserted_rows"] += len(batch)
                        result["leagues"][league]["upserted_rows"] += len(batch)
            result["status"] = "imported" if payloads else "no_eligible_matches"
        except Exception as exc:
            totals["failed_years"] += 1
            result["status"] = "failed"
            result["error"] = str(exc)[:240]
            errors.append(f"{year}: {str(exc)[:200]}")
            logger.exception("Tennis archive import failed for %s", year)
        by_year.append(result)

    missing_leagues = [
        league for league, counts in totals["by_league"].items()
        if counts["eligible_matches"] == 0
    ]
    successful = (
        totals["failed_years"] == 0
        and totals["valid_matches"] > 0
        and not missing_leagues
    )
    return {
        "success": successful,
        "status": (
            "completed" if successful
            else "no_eligible_matches" if totals["valid_matches"] == 0 and totals["failed_years"] == 0
            else "missing_league_data" if missing_leagues and totals["failed_years"] == 0
            else "partial_or_failed"
        ),
        "missing_leagues": missing_leagues,
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
    # The importer enforces competition-tier eligibility before persistence.
    # Do not re-filter persisted rows here: source labels can vary in casing or
    # spelling across annual files, while the archive table is already scoped.
    rows = list(unique.values())
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
                "Perfil descriptivo con fechas exactas y superficie desde Valuebetennis. "
                "Incluye Main Tour, Masters, Grand Slam y Challenger (ATP Challenger y WTA 125); "
                "excluye ITF. Esta tabla no alimenta las proyecciones ni los backtests Elo, "
                "que continúan usando su fuente histórica independiente. "
                "Esta fuente no publica estadísticas de saque; no se estiman ni se rellenan."
            ),
        },
    }



def _archive_rows_for_player(client, league: str, target: str, cutoff_date: date) -> list[dict[str, Any]]:
    columns = (
        "source_match_id,match_date,tournament,category,surface,round_code,"
        "player1_id,player1_name,player1_name_key,player2_id,player2_name,"
        "player2_name_key,winner_id,score"
    )
    first = (
        client.table(TABLE).select(columns)
        .eq("league", league).eq("player1_name_key", target)
        .lt("match_date", cutoff_date.isoformat())
        .order("match_date", desc=True).limit(1000).execute()
    ).data or []
    second = (
        client.table(TABLE).select(columns)
        .eq("league", league).eq("player2_name_key", target)
        .lt("match_date", cutoff_date.isoformat())
        .order("match_date", desc=True).limit(1000).execute()
    ).data or []
    unique = {}
    for row in first + second:
        key = str(row.get("source_match_id") or "")
        if key:
            unique[key] = row
    return list(unique.values())


def get_head_to_head_archive(
    player1_name: str,
    player2_name: str,
    league: str,
    cutoff_date: date,
) -> dict[str, Any]:
    """Return exact-ID H2H results from the persisted archive; never fuzzy-match."""
    first_key = normalize_player_name(player1_name)
    second_key = normalize_player_name(player2_name)
    selected_league = str(league or "").strip().upper()
    if selected_league not in SUPPORTED_LEAGUES:
        raise ValueError("league debe ser ATP o WTA.")
    if not first_key or not second_key or first_key == second_key:
        raise ValueError("Se necesitan dos nombres de jugadores distintos.")

    client = get_supabase_client()
    first_rows = _archive_rows_for_player(client, selected_league, first_key, cutoff_date)
    second_rows = _archive_rows_for_player(client, selected_league, second_key, cutoff_date)

    def resolve_player_id(rows: list[dict[str, Any]], key: str) -> set[str]:
        ids = set()
        for row in rows:
            if row.get("player1_name_key") == key and row.get("player1_id"):
                ids.add(str(row["player1_id"]))
            if row.get("player2_name_key") == key and row.get("player2_id"):
                ids.add(str(row["player2_id"]))
        return ids

    first_ids = resolve_player_id(first_rows, first_key)
    second_ids = resolve_player_id(second_rows, second_key)
    base = {
        "success": True,
        "league": selected_league,
        "player1_name": player1_name,
        "player2_name": player2_name,
        "cutoff_date_exclusive": cutoff_date.isoformat(),
        "source": "Valuebetennis ATP/WTA historical match archive",
        "source_attribution": SOURCE_ATTRIBUTION,
    }
    if len(first_ids) != 1 or len(second_ids) != 1:
        return {
            **base,
            "identity_ambiguous": len(first_ids) > 1 or len(second_ids) > 1,
            "identity_resolved": False,
            "message": (
                "La identidad de uno o ambos jugadores no pudo resolverse de forma unívoca."
                if first_ids or second_ids
                else "No hay historial suficiente de ambos jugadores en el archivo consultado."
            ),
            "total_matches": 0,
            "player1_wins": 0,
            "player2_wins": 0,
            "surface_breakdown": [],
            "recent_matches": [],
        }

    first_id = next(iter(first_ids))
    second_id = next(iter(second_ids))
    if first_id == second_id:
        return {
            **base,
            "identity_ambiguous": True,
            "identity_resolved": False,
            "message": "Los nombres resolvieron al mismo identificador de jugador.",
            "total_matches": 0,
            "player1_wins": 0,
            "player2_wins": 0,
            "surface_breakdown": [],
            "recent_matches": [],
        }

    matches_by_id = {}
    for row in first_rows:
        p1_id = str(row.get("player1_id") or "")
        p2_id = str(row.get("player2_id") or "")
        if {p1_id, p2_id} != {first_id, second_id}:
            continue
        winner_id = str(row.get("winner_id") or "")
        if winner_id not in {first_id, second_id}:
            continue
        match_id = str(row.get("source_match_id") or "")
        if match_id:
            matches_by_id[match_id] = row

    matches = sorted(
        matches_by_id.values(),
        key=lambda row: (str(row.get("match_date") or ""), str(row.get("source_match_id") or "")),
        reverse=True,
    )
    first_wins = sum(str(row.get("winner_id")) == first_id for row in matches)
    second_wins = len(matches) - first_wins
    surfaces: dict[str, dict[str, int]] = {}
    recent = []
    for row in matches:
        surface = str(row.get("surface") or "Sin dato")
        item = surfaces.setdefault(surface, {"surface": surface, "matches": 0, "player1_wins": 0, "player2_wins": 0})
        item["matches"] += 1
        winner_id = str(row.get("winner_id"))
        if winner_id == first_id:
            item["player1_wins"] += 1
        else:
            item["player2_wins"] += 1
        if len(recent) < 10:
            row_first_id = str(row.get("player1_id") or "")
            recent.append({
                "date": str(row.get("match_date") or ""),
                "tournament": row.get("tournament"),
                "category": row.get("category"),
                "surface": row.get("surface"),
                "round": str(row.get("round_code")) if row.get("round_code") is not None else None,
                "player1_name": player1_name if row_first_id == first_id else player2_name,
                "player2_name": player2_name if row_first_id == first_id else player1_name,
                "winner_name": player1_name if winner_id == first_id else player2_name,
                "result_for_player1": "W" if winner_id == first_id else "L",
                "score": str(row.get("score") or "").strip() or None,
            })

    return {
        **base,
        "identity_ambiguous": False,
        "identity_resolved": True,
        "message": None if matches else "No se encontraron enfrentamientos directos anteriores al partido.",
        "total_matches": len(matches),
        "player1_wins": first_wins,
        "player2_wins": second_wins,
        "surface_breakdown": sorted(surfaces.values(), key=lambda item: item["surface"]),
        "recent_matches": recent,
        "data_limitations": (
            "El H2H incluye únicamente partidos presentes en el archivo Valuebetennis: "
            "Main Tour, Masters, Grand Slam y Challenger; no representa necesariamente "
            "todos los enfrentamientos ITF ni toda la carrera de los jugadores."
        ),
    }
