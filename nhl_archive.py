"""Persistent, auditable NHL game-results archive.

The NHL public club schedule feed is undocumented. Imports preserve source
provenance and explicitly mark source terms as requiring review. This module
does not create predictions, modify model parameters, or import player stats.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from nhl_client import NHLDataError, get_team_season_schedule
from nhl_history_audit import CURRENT_TEAM_ABBREVIATIONS, build_season_coverage_report
from repository import get_supabase_client

logger = logging.getLogger(__name__)
TABLE = "nhl_game_archive"
UPSERT_BATCH_SIZE = 500
SOURCE_URL = "https://api-web.nhle.com/v1/club-schedule-season/{team}/{season}"
SOURCE_ATTRIBUTION = (
    "NHL public club season schedule feed; accessed through the NHL public web API. "
    "Source terms and permitted archival reuse remain under review."
)


class NHLArchiveImportError(RuntimeError):
    """Raised when a season cannot be safely normalized for persistence."""


def _valid_season(value: Any) -> str:
    season = str(value or "").strip()
    match = re.fullmatch(r"(\\d{4})(\\d{4})", season)
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise ValueError("season debe usar YYYYYYYY con años consecutivos.")
    return season


def _game_signature(game: dict[str, Any]) -> tuple[Any, ...]:
    home = game.get("home") or {}
    away = game.get("away") or {}
    return (
        game.get("game_date"),
        home.get("abbreviation"), away.get("abbreviation"),
        home.get("score"), away.get("score"),
        game.get("game_state"), game.get("game_type"),
        bool(game.get("completed")),
    )


def build_archive_payloads(
    season: str,
    schedule_by_team: dict[str, dict[str, Any]],
    imported_at: str,
) -> dict[str, Any]:
    """Deduplicate schedules, reject contradictions, and classify eligibility.

    Non-final games and preseason/exhibition games are retained for audit but
    are never marked eligible for model training. A non-final state is not
    assumed to mean cancelled; it remains NON_FINAL_REVIEW.
    """
    selected_season = _valid_season(season)
    observations: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for requested_team, payload in schedule_by_team.items():
        for game in (payload or {}).get("games", []):
            game_id = str(game.get("game_id") or "").strip()
            if not game_id:
                raise NHLArchiveImportError("Se encontró un partido sin game_id.")
            home = (game.get("home") or {}).get("abbreviation")
            away = (game.get("away") or {}).get("abbreviation")
            if requested_team not in {home, away}:
                raise NHLArchiveImportError(
                    f"El partido {game_id} no pertenece al calendario solicitado de {requested_team}."
                )
            observations.setdefault(game_id, []).append((requested_team, game))

    rows: list[dict[str, Any]] = []
    for game_id, entries in sorted(observations.items()):
        signatures = {_game_signature(game) for _, game in entries}
        if len(signatures) != 1:
            raise NHLArchiveImportError(
                f"El game_id {game_id} presenta datos contradictorios entre calendarios."
            )
        game = entries[0][1]
        home = game.get("home") or {}
        away = game.get("away") or {}
        game_date = str(game.get("game_date") or "").strip()
        game_type = game.get("game_type")
        if not re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}", game_date):
            raise NHLArchiveImportError(f"Fecha inválida para el partido {game_id}.")
        if game_type not in {1, 2, 3}:
            raise NHLArchiveImportError(f"game_type ausente o inválido para {game_id}.")
        home_abbr = str(home.get("abbreviation") or "").strip().upper()
        away_abbr = str(away.get("abbreviation") or "").strip().upper()
        if not home_abbr or not away_abbr or home_abbr == away_abbr:
            raise NHLArchiveImportError(f"Identidad de equipos inválida para {game_id}.")

        completed = bool(game.get("completed"))
        home_score = home.get("score")
        away_score = away.get("score")
        if completed and (
            isinstance(home_score, bool) or not isinstance(home_score, int)
            or isinstance(away_score, bool) or not isinstance(away_score, int)
            or home_score < 0 or away_score < 0
        ):
            raise NHLArchiveImportError(
                f"El partido completado {game_id} no contiene dos marcadores válidos."
            )

        observed_teams = sorted({team for team, _ in entries})
        cross_team_confirmed = len(observed_teams) >= 2
        both_nhl_franchises = (
            home_abbr in CURRENT_TEAM_ABBREVIATIONS
            and away_abbr in CURRENT_TEAM_ABBREVIATIONS
        )
        eligible = bool(
            completed and game_type in {2, 3}
            and cross_team_confirmed and both_nhl_franchises
        )
        if not completed:
            eligibility_reason = "non_final_result_not_eligible"
        elif game_type == 1:
            eligibility_reason = "preseason_or_exhibition_not_eligible"
        elif not both_nhl_franchises:
            eligibility_reason = "opponent_not_in_current_franchise_map"
        elif not cross_team_confirmed:
            eligibility_reason = "missing_cross_team_confirmation"
        else:
            eligibility_reason = "completed_regular_or_playoff_game_confirmed"

        rows.append({
            "game_id": game_id,
            "season": selected_season,
            "game_date": game_date,
            "start_time_utc": game.get("start_time_utc"),
            "home_team_id": home.get("id"),
            "home_team_abbreviation": home_abbr,
            "home_team_name": home.get("name"),
            "home_score": home_score,
            "away_team_id": away.get("id"),
            "away_team_abbreviation": away_abbr,
            "away_team_name": away.get("name"),
            "away_score": away_score,
            "game_type": game_type,
            "game_state": str(game.get("game_state") or "UNKNOWN").upper(),
            "result_status": "FINAL" if completed else "NON_FINAL_REVIEW",
            "cross_team_confirmed": cross_team_confirmed,
            "observed_teams": observed_teams,
            "training_eligible": eligible,
            "eligibility_reason": eligibility_reason,
            "source": "NHL public club season schedule",
            "source_url": SOURCE_URL.format(team="team-schedules", season=selected_season),
            "source_license": None,
            "source_terms_status": "review_required",
            "source_attribution": SOURCE_ATTRIBUTION,
            "imported_at": imported_at,
        })

    return {
        "rows": rows,
        "unique_games": len(rows),
        "training_eligible_games": sum(row["training_eligible"] for row in rows),
        "non_final_games": sum(row["result_status"] != "FINAL" for row in rows),
        "unconfirmed_games": sum(not row["cross_team_confirmed"] for row in rows),
        "excluded_game_types": {
            str(code): sum(row["game_type"] == code and not row["training_eligible"] for row in rows)
            for code in (1, 2, 3)
        },
    }


def import_nhl_season(season: str, client=None) -> dict[str, Any]:
    """Fetch all current-team schedules, validate fully, then idempotently upsert."""
    selected_season = _valid_season(season)
    schedules: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for team in CURRENT_TEAM_ABBREVIATIONS:
        try:
            schedules[team] = get_team_season_schedule(team, selected_season)
        except (NHLDataError, ValueError) as exc:
            failures[team] = str(exc)[:200]

    report = build_season_coverage_report(
        selected_season, list(CURRENT_TEAM_ABBREVIATIONS), schedules, failures
    )
    if (
        failures or report.get("missing_team_responses")
        or report.get("identity_conflicts")
        or report.get("completed_games_missing_score")
        or report.get("games_missing_game_type")
        or report.get("invalid_team_membership")
    ):
        raise NHLArchiveImportError(
            f"Auditoría estructural fallida para {selected_season}; no se escribió nada. "
            f"Fallos={len(failures)}, conflictos={len(report.get('identity_conflicts', []))}, "
            f"marcadores incompletos={len(report.get('completed_games_missing_score', []))}."
        )

    imported_at = datetime.now(timezone.utc).isoformat()
    parsed = build_archive_payloads(selected_season, schedules, imported_at)
    db = client or get_supabase_client()
    upserted = 0
    rows = parsed["rows"]
    for offset in range(0, len(rows), UPSERT_BATCH_SIZE):
        batch = rows[offset:offset + UPSERT_BATCH_SIZE]
        if batch:
            db.table(TABLE).upsert(batch, on_conflict="game_id").execute()
            upserted += len(batch)

    return {
        "success": True,
        "season": selected_season,
        "source": "NHL public club season schedule",
        "source_terms_status": "review_required",
        "persistence": "supabase_upsert",
        "team_schedules_succeeded": len(schedules),
        "schedule_observations": report["schedule_observations"],
        "cross_team_confirmation_rate": report["cross_team_confirmation_rate"],
        "review_required": report["review_required"],
        **{key: value for key, value in parsed.items() if key != "rows"},
        "upserted_rows": upserted,
        "audit_report": report,
    }


def sync_nhl_archive(start_season: str, end_season: str) -> dict[str, Any]:
    """Import an inclusive, consecutive season range; safe to rerun via game_id upsert."""
    start = _valid_season(start_season)
    end = _valid_season(end_season)
    start_year = int(start[:4])
    end_year = int(end[:4])
    if end_year < start_year or end_year - start_year > 10:
        raise ValueError("El rango debe ser ascendente y no superar 11 temporadas.")
    results = []
    errors = []
    for year in range(start_year, end_year + 1):
        season = f"{year}{year + 1}"
        try:
            results.append(import_nhl_season(season))
        except Exception as exc:
            logger.exception("NHL archive import failed for %s", season)
            errors.append({"season": season, "error": str(exc)[:240]})
            break
    return {
        "success": not errors and len(results) == end_year - start_year + 1,
        "start_season": start,
        "end_season": end,
        "seasons_imported": len(results),
        "total_upserted_rows": sum(item["upserted_rows"] for item in results),
        "by_season": results,
        "errors": errors,
        "source_terms_status": "review_required",
        "note": (
            "Los términos de reutilización de la fuente NHL siguen pendientes de revisión. "
            "Los registros no son una declaración de licencia abierta."
        ),
    }
