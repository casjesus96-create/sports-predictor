"""Football data endpoints backed by football-data.org v4."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from football_data_client import (
    LEAGUES,
    FootballDataError,
    get_competitions,
    get_matches,
    get_team_matches,
    get_match,
    get_match_head_to_head,
    get_standings,
)
from football_model import MODEL_VERSION, predict_1x2
from football_history import record_pregame_snapshot, settle_official_result
from football_h2h_experiment import evaluate_h2h_candidate, EXPERIMENT_VERSION
from football_backtest import run_chronological_backtest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/football", tags=["Football"])
MODEL_STATUS = "data_integration_only"
UTC = timezone.utc


def _provider_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except FootballDataError as exc:
        if exc.status_code == 400:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if exc.status_code == 429:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        if exc.status_code == 503:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        logger.warning("football-data.org request failed: %s", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected football data integration failure")
        raise HTTPException(
            status_code=502,
            detail="No fue posible consultar los datos de fútbol.",
        ) from exc


def _has_numeric_full_time(match: dict) -> bool:
    full_time = (match.get("score") or {}).get("fullTime") or {}
    return (
        isinstance(full_time.get("home"), int)
        and isinstance(full_time.get("away"), int)
    )


def _reconcile_match(selected_match: dict, history_by_id: dict) -> dict:
    """Prefer completed/current history data over a stale date-filter response."""
    item = dict(selected_match)
    historical = history_by_id.get(item.get("id"))
    if not historical:
        return item

    selected_status = str(item.get("status", "")).upper()
    historical_status = str(historical.get("status", "")).upper()
    historical_has_result = (
        historical_status in {"FINISHED", "AWARDED"}
        and _has_numeric_full_time(historical)
    )

    # A date-filtered fixture can lag behind the competition endpoint. When
    # history has a verified final score, use its status and score together.
    if historical_has_result:
        item["status"] = historical_status
        item["score"] = historical.get("score")
        for key in ("lastUpdated", "utcDate", "matchday", "stage"):
            if historical.get(key) is not None:
                item[key] = historical[key]
    elif selected_status not in {"FINISHED", "AWARDED"} and historical_status in {
        "IN_PLAY", "PAUSED", "EXTRA_TIME", "PENALTY_SHOOTOUT",
        "POSTPONED", "SUSPENDED", "CANCELLED",
    }:
        item["status"] = historical_status
        if historical.get("score") is not None:
            item["score"] = historical["score"]
    return item


@router.get("/health")
def football_health():
    """Reports integration configuration without exposing credentials."""
    import os

    return {
        "success": True,
        "provider": "football-data.org",
        "configured": bool(os.getenv("FOOTBALL_DATA_API_KEY", "").strip()),
        "model_status": MODEL_STATUS,
        "model_activated": False,
        "supported_competitions": list(LEAGUES.keys()),
    }


@router.get("/competitions")
def football_competitions():
    competitions = _provider_call(get_competitions)
    return {
        "success": True,
        "provider": "football-data.org",
        "generated_at": datetime.now(UTC).isoformat(),
        "competitions": competitions,
        "available_count": sum(1 for item in competitions if item["available_in_plan"]),
    }


@router.get("/games")
def football_games(
    competition: str = Query(..., description="Código de liga, por ejemplo PL o PD"),
    date_from: date | None = Query(None, alias="dateFrom"),
    date_to: date | None = Query(None, alias="dateTo"),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="dateFrom no puede ser posterior a dateTo.")
    if date_from and (date_from.year < 1990 or date_from.year > datetime.now(UTC).year + 2):
        raise HTTPException(status_code=400, detail="dateFrom fuera del rango admitido.")
    if date_to and (date_to.year < 1990 or date_to.year > datetime.now(UTC).year + 2):
        raise HTTPException(status_code=400, detail="dateTo fuera del rango admitido.")

    data = _provider_call(
        get_matches,
        competition,
        date_from.isoformat() if date_from else None,
        date_to.isoformat() if date_to else None,
    )
    matches = data.get("matches", [])

    # Query competition history separately: selected-date results are fixtures,
    # not a sufficient training sample and can lag behind final score updates.
    history = _provider_call(get_matches, competition)
    history_matches = history.get("matches", [])
    history_by_id = {
        match.get("id"): match for match in history_matches if match.get("id") is not None
    }
    reconciled_matches = [
        _reconcile_match(match, history_by_id) for match in matches
    ]

    # The date-filtered list and competition history can both lag behind.
    # Fetch individual details only for suspicious matches, not every fixture,
    # and rely on the client's TTL cache to protect the free API quota.
    refreshed_matches = []
    # Keep detail refreshes bounded: each request already calls the date list
    # and competition history. Unbounded per-match lookups can exhaust the
    # provider quota and make later fixtures lose fresh scores.
    detail_refresh_budget = 2
    detail_refreshes = 0
    for match in reconciled_matches:
        status = str(match.get("status", "")).upper()
        kickoff = match.get("utcDate")
        kickoff_passed = False
        if kickoff:
            try:
                kickoff_dt = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
                if kickoff_dt.tzinfo is None:
                    kickoff_dt = kickoff_dt.replace(tzinfo=UTC)
                kickoff_passed = kickoff_dt <= datetime.now(UTC)
            except (TypeError, ValueError):
                logger.warning("Invalid kickoff datetime for football match %s", match.get("id"))

        # Refresh every already-started fixture whose status is not terminal,
        # even if the stale payload contains a partial/placeholder score.
        # This is important when the competition/date endpoints disagree.
        needs_detail = (
            status in {"FINISHED", "AWARDED"} and not _has_numeric_full_time(match)
        ) or (
            status in {"SCHEDULED", "TIMED", "IN_PLAY", "PAUSED",
                       "EXTRA_TIME", "PENALTY_SHOOTOUT"}
            and kickoff_passed
            and match.get("id") is not None
        )
        if needs_detail and detail_refreshes < detail_refresh_budget:
            detail_refreshes += 1
            try:
                detail = _provider_call(get_match, int(match["id"]))
                detail_match = detail.get("match", detail)
                if (
                    detail_match.get("id") == match.get("id")
                    and str(detail_match.get("status", "")).upper() in {"FINISHED", "AWARDED"}
                    and _has_numeric_full_time(detail_match)
                ):
                    match = dict(match)
                    match["status"] = str(detail_match["status"]).upper()
                    match["score"] = detail_match.get("score")
                    for key in ("lastUpdated", "utcDate", "matchday", "stage"):
                        if detail_match.get(key) is not None:
                            match[key] = detail_match[key]
                elif detail_match.get("id") == match.get("id") and str(detail_match.get("status", "")).upper() in {
                    "IN_PLAY", "PAUSED", "EXTRA_TIME", "PENALTY_SHOOTOUT",
                    "POSTPONED", "SUSPENDED", "CANCELLED",
                }:
                    match = dict(match)
                    match["status"] = str(detail_match["status"]).upper()
                    if detail_match.get("score") is not None:
                        match["score"] = detail_match["score"]
            except HTTPException as exc:
                # A detail lookup is best-effort. Keep the list/history result
                # usable if the provider blocks the optional request.
                logger.warning("Could not refresh football match %s: %s", match.get("id"), exc.detail)
        refreshed_matches.append(match)
    reconciled_matches = refreshed_matches

    completed = [
        match for match in history_matches
        if str(match.get("status", "")).upper() == "FINISHED"
        and _has_numeric_full_time(match)
    ]

    enriched_matches = []
    for match in reconciled_matches:
        item = dict(match)
        status = str(item.get("status", "")).upper()
        home = (item.get("homeTeam") or {}).get("name")
        away = (item.get("awayTeam") or {}).get("name")
        if status in {"SCHEDULED", "TIMED"} and home and away:
            try:
                item["prediction"] = predict_1x2(home, away, completed)
            except (TypeError, ValueError):
                item["prediction"] = {
                    "available": False,
                    "reason": "No se pudo calcular una estimación válida con los datos disponibles.",
                }
        else:
            item["prediction"] = {
                "available": False,
                "reason": "Las probabilidades prepartido solo se muestran para encuentros no iniciados.",
            }

        # Persist the original pre-match estimate once; never overwrite it after kickoff.
        if status in {"SCHEDULED", "TIMED"} and item.get("prediction", {}).get("available"):
            record_pregame_snapshot(item, competition, item["prediction"])

        # Only official full-time numeric scores can settle a previously saved snapshot.
        settle_official_result(item, competition)
        enriched_matches.append(item)

    return {
        "success": True,
        "provider": "football-data.org",
        "competition": competition.upper(),
        "generated_at": datetime.now(UTC).isoformat(),
        "count": data.get("resultSet", {}).get("count", len(matches)),
        "filters": {
            "dateFrom": date_from.isoformat() if date_from else None,
            "dateTo": date_to.isoformat() if date_to else None,
        },
        "prediction_model": MODEL_VERSION,
        "training_sample": {
            "completed_matches": len(completed),
            "source": "historial de la competición devuelto por el proveedor",
        },
        "matches": enriched_matches,
    }


@router.get("/head-to-head")
def football_head_to_head(
    competition: str = Query(..., description="Código de liga, por ejemplo PL o PD"),
    home_team_id: int = Query(..., gt=0),
    away_team_id: int = Query(..., gt=0),
    match_id: int | None = Query(None, gt=0),
    limit: int = Query(10, ge=1, le=50),
):
    """Historical meetings found in each team's recent finished fixtures."""
    if home_team_id == away_team_id:
        raise HTTPException(status_code=400, detail="Los equipos deben ser distintos.")
    code = competition.strip().upper()
    if code not in LEAGUES:
        raise HTTPException(status_code=400, detail=f"Competición no admitida. Usa uno de estos códigos: {', '.join(LEAGUES)}.")

    # Query both teams' result feeds because either feed can be truncated.
    home_data = _provider_call(get_team_matches, home_team_id, 500)
    away_data = _provider_call(get_team_matches, away_team_id, 500)
    candidates = {}
    for payload in (home_data, away_data):
        for match in payload.get("matches", []):
            match_id = match.get("id")
            if match_id is not None:
                candidates[match_id] = match

    meetings = []
    for match in candidates.values():
        if str(match.get("status", "")).upper() not in {"FINISHED", "AWARDED"}:
            continue
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}
        if {home.get("id"), away.get("id")} != {home_team_id, away_team_id}:
            continue
        score = (match.get("score") or {}).get("fullTime") or {}
        hs, aws = score.get("home"), score.get("away")
        if (
            not isinstance(hs, int) or isinstance(hs, bool)
            or not isinstance(aws, int) or isinstance(aws, bool)
        ):
            continue
        winner = "draw" if hs == aws else ("home" if hs > aws else "away")
        comp = match.get("competition") or {}
        meetings.append({
            "id": match.get("id"),
            "date": match.get("utcDate"),
            "competition": (match.get("competition") or {}).get("name"),
            "competition_code": (match.get("competition") or {}).get("code"),
            "home_team": home.get("name"),
            "home_team_id": home.get("id"),
            "away_team": away.get("name"),
            "away_team_id": away.get("id"),
            "home_score": hs,
            "away_score": aws,
            "total_goals": hs + aws,
            "winner": winner,
            "matchday": match.get("matchday"),
            "stage": match.get("stage"),
            "venue": match.get("venue"),
            "half_time": (match.get("score") or {}).get("halfTime"),
            "duration": (match.get("score") or {}).get("duration"),
            "result_source": source,
        })

    # Deduplicate by fixture ID in case the upstream payload repeats a match.
    unique = {row["id"]: row for row in meetings if row.get("id") is not None}
    meetings = list(unique.values())
    meetings.sort(key=lambda row: str(row.get("date") or ""), reverse=True)

    home_wins = draws = away_wins = home_goals = away_goals = total_goals = 0
    for row in meetings:
        if row["home_team_id"] == home_team_id:
            home_goals += row["home_score"]
            away_goals += row["away_score"]
            result_for_home = row["winner"]
        else:
            home_goals += row["away_score"]
            away_goals += row["home_score"]
            result_for_home = "away" if row["winner"] == "home" else "home" if row["winner"] == "away" else "draw"
        if result_for_home == "home":
            home_wins += 1
        elif result_for_home == "away":
            away_wins += 1
        else:
            draws += 1
        total_goals += row["total_goals"]

    count = len(meetings)
    return {
        "success": True,
        "provider": "football-data.org",
        "competition": code,
        "history_scope": "Enfrentamientos directos finalizados encontrados en los últimos resultados disponibles de ambos equipos, incluyendo competiciones distintas. La profundidad depende de la cobertura y los límites del proveedor.",
        "teams": {"home": {"id": home_team_id}, "away": {"id": away_team_id}},
        "sample_size": count,
        "summary": {
            "home_team_wins": home_wins,
            "draws": draws,
            "away_team_wins": away_wins,
            "home_team_goals": home_goals,
            "away_team_goals": away_goals,
            "average_home_team_goals": round(home_goals / count, 3) if count else None,
            "average_away_team_goals": round(away_goals / count, 3) if count else None,
            "average_total_goals": round(total_goals / count, 3) if count else None,
            "both_teams_scored_count": sum(1 for row in meetings if row["home_score"] > 0 and row["away_score"] > 0),
            "over_2_5_count": sum(1 for row in meetings if row["total_goals"] >= 3),
            "under_2_5_count": sum(1 for row in meetings if row["total_goals"] <= 2),
        },
        "meetings": meetings[:limit],
        "returned_matches": min(count, limit),
    }


@router.get("/experimental-h2h")
def football_experimental_h2h(
    competition: str = Query(..., description="Código de liga, por ejemplo BL1"),
    home_team_id: int = Query(..., gt=0),
    away_team_id: int = Query(..., gt=0),
    match_id: int = Query(..., gt=0),
    home_team: str = Query(..., min_length=1, max_length=120),
    away_team: str = Query(..., min_length=1, max_length=120),
    kickoff_at: str = Query(..., min_length=10, max_length=40),
):
    """Compare the official baseline with the isolated H2H candidate on demand."""
    if home_team_id == away_team_id or home_team.strip().casefold() == away_team.strip().casefold():
        raise HTTPException(status_code=400, detail="Los equipos deben ser distintos.")

    try:
        kickoff = datetime.fromisoformat(kickoff_at.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="kickoff_at no es una fecha ISO 8601 válida.") from exc
    if kickoff.tzinfo is None:
        raise HTTPException(status_code=400, detail="kickoff_at debe incluir zona horaria.")
    if kickoff <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="El análisis H2H experimental solo está disponible antes del inicio.")

    competition_data = _provider_call(get_matches, competition)
    completed = [
        item for item in competition_data.get("matches", [])
        if str(item.get("status", "")).upper() == "FINISHED" and _has_numeric_full_time(item)
        and (item.get("utcDate") and datetime.fromisoformat(str(item["utcDate"]).replace("Z", "+00:00")) < kickoff)
    ]
    base = predict_1x2(home_team.strip(), away_team.strip(), completed)
    h2h = football_head_to_head(
        competition=competition,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        match_id=match_id,
        limit=50,
    )
    normalized_meetings = []
    for meeting in h2h.get("meetings", []):
        # Normalize historical aliases to the exact target fixture names using
        # provider team IDs, while preserving each historical home/away order.
        historical_home_name = home_team.strip() if meeting.get("home_team_id") == home_team_id else away_team.strip()
        historical_away_name = away_team.strip() if meeting.get("away_team_id") == away_team_id else home_team.strip()
        normalized_meetings.append({
            "id": meeting.get("id"),
            "status": "FINISHED",
            "utcDate": meeting.get("date"),
            "homeTeam": {"name": historical_home_name},
            "awayTeam": {"name": historical_away_name},
            "score": {"fullTime": {
                "home": meeting.get("home_score"),
                "away": meeting.get("away_score"),
            }},
        })
    candidate = evaluate_h2h_candidate(
        home_team.strip(),
        away_team.strip(),
        kickoff_at,
        base,
        normalized_meetings,
    )
    return {
        "success": True,
        "experiment_version": EXPERIMENT_VERSION,
        "mode": "SHADOW_ONLY",
        "official_model_version": MODEL_VERSION,
        "base_prediction": base,
        "candidate": candidate,
        "h2h_sample_size": candidate.get("h2h", {}).get("valid_meetings", 0),
        "note": "La comparación es experimental; no cambia las probabilidades oficiales ni guarda ni sobrescribe snapshots.",
    }


@router.get("/backtest")
def football_chronological_backtest(
    competition: str = Query(..., description="Código de liga, por ejemplo PL o PD"),
    include_external_h2h: bool = Query(
        False,
        description="Consulta H2H externo para una muestra de hasta 10 partidos, con límite de solicitudes.",
    ),
):
    """Evaluate official Poisson vs H2H candidate chronologically, read-only."""
    data = _provider_call(get_matches, competition)
    matches = data.get("matches", [])
    external_h2h_by_match_id: dict[int, list[dict]] = {}
    external_h2h_attempted = 0
    external_h2h_failed = 0

    if include_external_h2h:
        eligible_targets = []
        for match in matches:
            kickoff = _parse_football_datetime(match.get("utcDate") or match.get("date"))
            if (
                kickoff is not None
                and str(match.get("status", "")).upper() == "FINISHED"
                and _has_numeric_full_time(match)
                and isinstance(match.get("id"), int)
                and (match.get("homeTeam") or {}).get("id")
                and (match.get("awayTeam") or {}).get("id")
            ):
                eligible_targets.append((kickoff, match))
        eligible_targets.sort(key=lambda row: (row[0], row[1]["id"]))
        cap = min(10, len(eligible_targets))
        if cap:
            indices = sorted({round(i * (len(eligible_targets) - 1) / max(1, cap - 1)) for i in range(cap)})
            for index in indices:
                target = eligible_targets[index][1]
                external_h2h_attempted += 1
                try:
                    payload = _provider_call(get_match_head_to_head, int(target["id"]), 50)
                    normalized_meetings = []
                    target_home = target["homeTeam"]
                    target_away = target["awayTeam"]
                    home_id, away_id = target_home["id"], target_away["id"]
                    for meeting in payload.get("matches", []):
                        historical_home = meeting.get("homeTeam") or {}
                        historical_away = meeting.get("awayTeam") or {}
                        if {historical_home.get("id"), historical_away.get("id")} != {home_id, away_id}:
                            continue
                        score = (meeting.get("score") or {}).get("fullTime") or {}
                        hs, aws = score.get("home"), score.get("away")
                        if (
                            str(meeting.get("status", "")).upper() != "FINISHED"
                            or not isinstance(hs, int) or isinstance(hs, bool) or hs < 0
                            or not isinstance(aws, int) or isinstance(aws, bool) or aws < 0
                        ):
                            continue
                        normalized_meetings.append({
                            "id": meeting.get("id"),
                            "status": "FINISHED",
                            "utcDate": meeting.get("utcDate"),
                            "homeTeam": {"name": target_home["name"] if historical_home.get("id") == home_id else target_away["name"]},
                            "awayTeam": {"name": target_away["name"] if historical_away.get("id") == away_id else target_home["name"]},
                            "score": {"fullTime": {"home": hs, "away": aws}},
                        })
                    external_h2h_by_match_id[int(target["id"])] = normalized_meetings
                except HTTPException as exc:
                    external_h2h_failed += 1
                    logger.warning("External H2H backtest lookup failed for match %s: %s", target.get("id"), exc.detail)
                    if exc.status_code == 429:
                        # Stop immediately when the provider signals quota exhaustion.
                        break

    result = run_chronological_backtest(matches, external_h2h_by_match_id)
    result["external_h2h_lookup"] = {
        "requested": include_external_h2h,
        "request_cap": 10,
        "attempted": external_h2h_attempted,
        "failed": external_h2h_failed,
        "successful": external_h2h_attempted - external_h2h_failed,
        "fixtures_with_external_h2h_payload": len(external_h2h_by_match_id),
    }
    return {
        "success": True,
        "provider": "football-data.org",
        "competition": competition.strip().upper(),
        "generated_at": datetime.now(UTC).isoformat(),
        "history_scope": (
            "Historial de la competición disponible en el plan. Si se activa H2H externo, "
            "se consultan como máximo 10 partidos distribuidos cronológicamente; solo esos "
            "objetivos usan H2H externo. Los demás usan la competición seleccionada. "
            "Todos los enfrentamientos H2H se filtran para excluir fechas iguales o posteriores "
            "al kickoff del partido evaluado; no se escriben snapshots."
        ),
        "backtest": result,
    }


def _parse_football_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed
    except (TypeError, ValueError):
        return None


@router.get("/standings")
def football_standings(
    competition: str = Query(..., description="Código de liga, por ejemplo PL o PD"),
):
    data = _provider_call(get_standings, competition)
    return {
        "success": True,
        "provider": "football-data.org",
        "competition": competition.upper(),
        "generated_at": datetime.now(UTC).isoformat(),
        "standings": data.get("standings", []),
        "season": data.get("season"),
    }
