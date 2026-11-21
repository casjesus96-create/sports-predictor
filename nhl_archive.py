"""Source-neutral NHL archive normalization.

No data provider is approved by this module. It only validates and normalizes
already obtained schedule rows after a human has reviewed the source terms.
It does not fetch data or write to a database.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from nhl_team_identity_registry import build_season_team_identity_map

CURRENT_TEAM_ABBREVIATIONS = frozenset({
    "ANA", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ",
    "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NSH",
    "NJD", "NYI", "NYR", "OTT", "PHI", "PIT", "SJS", "SEA",
    "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WSH", "WPG",
})


class NHLArchiveImportError(RuntimeError):
    """Raised when a season cannot be safely normalized for persistence."""


def _valid_season(value: Any) -> str:
    season = str(value or "").strip()
    match = re.fullmatch(r"([0-9]{4})([0-9]{4})", season)
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise ValueError("season debe usar YYYYYYYY con años consecutivos.")
    return season


def _game_signature(game: dict[str, Any]) -> tuple[Any, ...]:
    home = game.get("home") or {}
    away = game.get("away") or {}
    return (
        game.get("game_date"),
        game.get("start_time_utc"),
        home.get("id"), home.get("abbreviation"), home.get("name"), home.get("score"),
        away.get("id"), away.get("abbreviation"), away.get("name"), away.get("score"),
        game.get("game_state"), game.get("game_type"),
        game.get("completed"),
    )


def build_archive_payloads(
    season: str,
    schedule_by_team: dict[str, dict[str, Any]],
    imported_at: str,
    source_name: str,
    source_url: str,
    source_license: str,
    source_attribution: str,
    source_terms_status: str,
    team_identity_by_abbreviation: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Deduplicate schedules, reject contradictions, and classify eligibility.

    Non-final games and preseason/exhibition games are retained for audit but
    are never marked eligible for model training. A non-final state is not
    assumed to mean cancelled; it remains NON_FINAL_REVIEW.
    """
    selected_season = _valid_season(season)
    provenance = (source_name, source_url, source_license, source_attribution)
    if any(not str(value or "").strip() for value in provenance):
        raise ValueError("La fuente, URL, licencia y atribución son obligatorias.")
    if source_terms_status != "reviewed":
        raise ValueError("No se puede preparar una importación sin revisión de términos de la fuente.")
    if not isinstance(schedule_by_team, dict):
        raise NHLArchiveImportError("Los calendarios por equipo deben ser un objeto.")
    # Resolve only abbreviations valid in this exact season. Historical aliases
    # come from the reviewed registry; unknown/out-of-period codes stay ineligible.
    registry_season = f"{selected_season[:4]}-{selected_season[4:]}"
    identity_map = build_season_team_identity_map(registry_season)
    if team_identity_by_abbreviation is not None:
        if not isinstance(team_identity_by_abbreviation, dict):
            raise NHLArchiveImportError("El mapa de identidades NHL debe ser un objeto.")
        for abbreviation, canonical_key in team_identity_by_abbreviation.items():
            abbr = str(abbreviation or "").strip().upper()
            key = str(canonical_key or "").strip().upper()
            if not abbr or not key:
                raise NHLArchiveImportError("Cada identidad histórica requiere abreviatura y clave canónica.")
            identity_map[abbr] = key

    observations: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for requested_team, payload in schedule_by_team.items():
        team_key = str(requested_team or "").strip().upper()
        if not team_key:
            raise NHLArchiveImportError("Se encontró un calendario sin equipo solicitado.")
        if not isinstance(payload, dict):
            raise NHLArchiveImportError(f"El calendario de {team_key} tiene un formato inválido.")
        games = payload.get("games", [])
        if not isinstance(games, list):
            raise NHLArchiveImportError(f"La lista de partidos de {team_key} tiene un formato inválido.")
        for game in games:
            if not isinstance(game, dict):
                raise NHLArchiveImportError(f"El calendario de {team_key} contiene un partido inválido.")
            game_id = str(game.get("game_id") or "").strip()
            if not game_id:
                raise NHLArchiveImportError("Se encontró un partido sin game_id.")
            completed = game.get("completed")
            if not isinstance(completed, bool):
                raise NHLArchiveImportError(
                    f"El indicador completed del partido {game_id} debe ser booleano."
                )
            game_type = game.get("game_type")
            if isinstance(game_type, bool) or not isinstance(game_type, int) or game_type not in {1, 2, 3}:
                raise NHLArchiveImportError(f"game_type ausente o inválido para {game_id}.")
            home = game.get("home")
            away = game.get("away")
            if not isinstance(home, dict) or not isinstance(away, dict):
                raise NHLArchiveImportError(f"Identidad de equipos inválida para {game_id}.")
            home_abbr = str(home.get("abbreviation") or "").strip().upper()
            away_abbr = str(away.get("abbreviation") or "").strip().upper()
            if team_key not in {home_abbr, away_abbr}:
                raise NHLArchiveImportError(
                    f"El partido {game_id} no pertenece al calendario solicitado de {team_key}."
                )
            observations.setdefault(game_id, []).append((team_key, game))

    rows: list[dict[str, Any]] = []
    for game_id, entries in sorted(observations.items()):
        signatures = {_game_signature(game) for _, game in entries}
        if len(signatures) != 1:
            raise NHLArchiveImportError(
                f"El game_id {game_id} presenta datos contradictorios entre calendarios."
            )
        game = entries[0][1]
        home = game["home"]
        away = game["away"]
        game_date = str(game.get("game_date") or "").strip()
        game_type = game["game_type"]
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", game_date):
            raise NHLArchiveImportError(f"Fecha inválida para el partido {game_id}.")
        try:
            date.fromisoformat(game_date)
        except ValueError as exc:
            raise NHLArchiveImportError(f"Fecha inválida para el partido {game_id}.") from exc
        season_start = int(selected_season[:4])
        if not (f"{season_start}-07-01" <= game_date <= f"{season_start + 1}-06-30"):
            raise NHLArchiveImportError(f"El partido {game_id} está fuera del rango de su temporada.")
        home_abbr = str(home.get("abbreviation") or "").strip().upper()
        away_abbr = str(away.get("abbreviation") or "").strip().upper()
        if not home_abbr or not away_abbr or home_abbr == away_abbr:
            raise NHLArchiveImportError(f"Identidad de equipos inválida para {game_id}.")

        completed = game["completed"]
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
        home_canonical_key = identity_map.get(home_abbr)
        away_canonical_key = identity_map.get(away_abbr)
        both_nhl_franchises = bool(home_canonical_key and away_canonical_key)
        eligible = bool(
            completed and game_type in {2, 3}
            and cross_team_confirmed and both_nhl_franchises
        )
        if not completed:
            eligibility_reason = "non_final_result_not_eligible"
        elif game_type == 1:
            eligibility_reason = "preseason_or_exhibition_not_eligible"
        elif not both_nhl_franchises:
            eligibility_reason = "team_identity_mapping_incomplete"
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
            "home_team_canonical_key": home_canonical_key,
            "home_team_name": home.get("name"),
            "home_score": home_score,
            "away_team_id": away.get("id"),
            "away_team_abbreviation": away_abbr,
            "away_team_canonical_key": away_canonical_key,
            "away_team_name": away.get("name"),
            "away_score": away_score,
            "game_type": game_type,
            "game_state": str(game.get("game_state") or "UNKNOWN").upper(),
            "result_status": "FINAL" if completed else "NON_FINAL_REVIEW",
            "cross_team_confirmed": cross_team_confirmed,
            "observed_teams": observed_teams,
            "training_eligible": eligible,
            "eligibility_reason": eligibility_reason,
            "source": source_name,
            "source_url": source_url,
            "source_license": source_license,
            "source_terms_status": source_terms_status,
            "source_attribution": source_attribution,
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
