"""Batter-versus-pitcher pregame context using MLB Stats API.

Official lineups are preferred; a prior-game batting order may be shown only as
an explicitly unconfirmed reference. This module never changes the official
MLB 2.0.0-matchup win probabilities.
"""
from datetime import datetime, timedelta, timezone

import requests

MLB_API = "https://statsapi.mlb.com/api/v1"
HEADERS = {
    "User-Agent": "Sports-Predictor/1.0",
    "Accept": "application/json",
}
TIMEOUT_SECONDS = 20


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value):
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _empty_stats():
    return {
        "available": False,
        "plate_appearances": 0,
        "at_bats": 0,
        "hits": 0,
        "home_runs": 0,
        "doubles": 0,
        "triples": 0,
        "walks": 0,
        "hit_by_pitch": 0,
        "sacrifice_flies": 0,
        "avg": None,
        "slg": None,
        "ops": None,
        "sample_size": 0,
        "reason": "No hay enfrentamientos directos registrados en los datos disponibles.",
    }


def extract_confirmed_lineup(feed, side):
    """Return the confirmed batting order, or [] when MLB has not published it."""
    if side not in ("home", "away"):
        raise ValueError("side debe ser 'home' o 'away'.")

    live_data = feed.get("liveData") or {}
    boxscore = live_data.get("boxscore") or {}
    teams = boxscore.get("teams") or {}
    team_data = teams.get(side) or {}
    batting_order = team_data.get("battingOrder") or []
    players = team_data.get("players") or []

    if not batting_order or not isinstance(players, dict):
        return []

    lineup = []
    for index, raw_player_id in enumerate(batting_order, start=1):
        player_id = _safe_int(raw_player_id)
        if player_id is None:
            continue

        player_entry = players.get(f"ID{player_id}") or players.get(str(player_id)) or {}
        person = player_entry.get("person") or {}
        resolved_id = _safe_int(person.get("id")) or player_id
        name = person.get("fullName") or person.get("name")

        if not name:
            continue

        lineup.append({
            "player_id": resolved_id,
            "player_name": name,
            "batting_order": index,
            "position": (player_entry.get("position") or {}).get("abbreviation"),
        })

    return lineup


def normalize_batter_pitcher_stats(splits):
    """Normalize one or more MLB Stats API vsPlayer splits without inventing values."""
    splits = [split for split in (splits or []) if isinstance(split, dict) and isinstance(split.get("stat"), dict)]
    if not splits:
        return _empty_stats()

    fields = {
        "at_bats": "atBats",
        "hits": "hits",
        "home_runs": "homeRuns",
        "doubles": "doubles",
        "triples": "triples",
        "walks": "baseOnBalls",
        "hit_by_pitch": "hitByPitch",
        "sacrifice_flies": "sacFlies",
        "plate_appearances": "plateAppearances",
    }
    totals = {key: 0 for key in fields}
    found_counts = False

    for split in splits:
        stat = split.get("stat") or {}
        for output_key, source_key in fields.items():
            value = _safe_int(stat.get(source_key))
            if value is not None:
                totals[output_key] += value
                found_counts = True

    at_bats = totals["at_bats"]
    hits = totals["hits"]
    doubles = totals["doubles"]
    triples = totals["triples"]
    home_runs = totals["home_runs"]
    walks = totals["walks"]
    hit_by_pitch = totals["hit_by_pitch"]
    sacrifice_flies = totals["sacrifice_flies"]

    if not found_counts:
        # Some API responses provide rate stats but no counting stats.
        stat = splits[0].get("stat") or {}
        result = _empty_stats()
        for key in ("avg", "slg", "ops"):
            result[key] = _safe_float(stat.get(key))
        sample = _safe_int(stat.get("plateAppearances"))
        result["sample_size"] = sample or 0
        result["plate_appearances"] = sample or 0
        result["available"] = bool(sample or any(result[k] is not None for k in ("avg", "slg", "ops")))
        result["reason"] = None if result["available"] else _empty_stats()["reason"]
        return result

    total_bases = (
        (hits - doubles - triples - home_runs)
        + (2 * doubles)
        + (3 * triples)
        + (4 * home_runs)
    )
    # MLB totals are sometimes incomplete for rate-stat fields; never divide by zero.
    avg = hits / at_bats if at_bats > 0 else None
    slg = total_bases / at_bats if at_bats > 0 else None
    obp_denominator = at_bats + walks + hit_by_pitch + sacrifice_flies
    obp = (hits + walks + hit_by_pitch) / obp_denominator if obp_denominator > 0 else None
    ops = obp + slg if obp is not None and slg is not None else None
    plate_appearances = totals["plate_appearances"] or obp_denominator
    sample_size = plate_appearances or at_bats

    available = sample_size > 0
    return {
        "available": available,
        **totals,
        "avg": round(avg, 3) if avg is not None else None,
        "slg": round(slg, 3) if slg is not None else None,
        "ops": round(ops, 3) if ops is not None else None,
        "sample_size": sample_size,
        "reason": None if available else _empty_stats()["reason"],
    }


def _fetch_vs_pitcher_stats(player_ids, pitcher_id):
    """Fetch all listed hitters against one opposing pitcher in a single bulk request."""
    if not player_ids or not pitcher_id:
        return {}

    params = {
        "personIds": ",".join(str(player_id) for player_id in player_ids),
        "hydrate": (
            "stats(group=[hitting],type=[vsPlayer],"
            f"opposingPlayerId={int(pitcher_id)})"
        ),
    }
    response = requests.get(
        f"{MLB_API}/people",
        params=params,
        timeout=TIMEOUT_SECONDS,
        headers=HEADERS,
    )
    response.raise_for_status()
    data = response.json()

    result = {}
    for person in data.get("people") or []:
        player_id = _safe_int(person.get("id"))
        if player_id is None:
            continue

        stat_groups = person.get("stats") or []
        splits = []
        for stat_group in stat_groups:
            group_name = (stat_group.get("group") or {}).get("displayName", "")
            type_name = (stat_group.get("type") or {}).get("displayName", "")
            # Some API responses omit display labels for hydrated stats.
            if group_name and group_name.lower() != "hitting":
                continue
            if type_name and "player" not in type_name.lower():
                continue
            splits.extend(stat_group.get("splits") or [])

        result[player_id] = normalize_batter_pitcher_stats(splits)

    return result


def _team_matchup(
    feed,
    batting_side,
    opposing_pitcher,
    opposing_team_name,
    lineup_source="game_feed",
    lineup_override=None,
    lineup_source_game_date=None,
):
    lineup = lineup_override if lineup_override is not None else extract_confirmed_lineup(feed, batting_side)
    lineup_confirmed = bool(lineup) and lineup_source != "previous_game_reference"
    pitcher_id = _safe_int((opposing_pitcher or {}).get("pitcher_id") or (opposing_pitcher or {}).get("id"))
    pitcher_name = (opposing_pitcher or {}).get("pitcher_name") or (opposing_pitcher or {}).get("name")

    base = {
        "available": False,
        "lineup_confirmed": lineup_confirmed,
        "lineup_status": "confirmed" if lineup_confirmed else ("estimated_from_previous_game" if lineup else "not_found"),
        "batting_side": batting_side,
        "opposing_pitcher": {
            "player_id": pitcher_id,
            "name": pitcher_name,
            "team": opposing_team_name,
        },
        "hitters": [],
        "lineup_source": lineup_source,
    }
    if lineup_source_game_date:
        base["lineup_source_game_date"] = lineup_source_game_date

    if not lineup:
        base["reason"] = (
            "No se encontró el orden al bate en el feed ni en el boxscore de MLB, "
            "y no hubo una alineación reciente utilizable como referencia."
        )
        return base

    if not lineup_confirmed:
        base["reason"] = (
            "Alineación de referencia basada en el último partido anterior disponible; "
            "no está confirmada ni proyectada oficialmente para este encuentro y puede cambiar."
        )

    if not pitcher_id:
        base["hitters"] = [
            {**hitter, "vs_pitcher": _empty_stats()} for hitter in lineup
        ]
        base["reason"] = "No se ha identificado el pitcher abridor rival; no se puede calcular el enfrentamiento directo."
        return base

    stats_by_player = _fetch_vs_pitcher_stats(
        [hitter["player_id"] for hitter in lineup],
        pitcher_id,
    )
    hitters = []
    for hitter in lineup:
        stats = stats_by_player.get(hitter["player_id"], _empty_stats())
        hitters.append({**hitter, "vs_pitcher": stats})

    base["hitters"] = hitters
    base["available"] = any(hitter["vs_pitcher"].get("available") for hitter in hitters)
    if base["available"]:
        base["reason"] = None
    elif lineup_confirmed:
        base["reason"] = "Alineación confirmada, pero no hay historial directo suficiente disponible para los bateadores."
    else:
        base["reason"] = (
            "Alineación de referencia basada en el último partido anterior disponible; "
            "no está confirmada ni proyectada oficialmente para este encuentro y puede cambiar. "
            "No hay historial directo suficiente disponible para los bateadores."
        )
    base["scope"] = "career_vs_pitcher"
    base["generated_at"] = datetime.now(timezone.utc).isoformat()
    return base




def _fetch_active_roster(team_id):
    """Fetch active roster; fall back to the 40-man roster without mislabeling it."""
    if not team_id:
        return {
            "available": False,
            "players": [],
            "source": "MLB Stats API",
            "reason": "No se identificó el equipo.",
        }

    errors = []
    for roster_type in ("active", "40Man"):
        try:
            response = requests.get(
                f"{MLB_API}/teams/{int(team_id)}/roster",
                params={"rosterType": roster_type},
                timeout=TIMEOUT_SECONDS,
                headers=HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
            players = []
            for entry in payload.get("roster") or []:
                person = entry.get("person") or {}
                player_id = _safe_int(person.get("id"))
                name = person.get("fullName") or person.get("name")
                if not player_id or not name:
                    continue
                position = entry.get("position") or {}
                players.append({
                    "player_id": player_id,
                    "player_name": name,
                    "position": position.get("abbreviation") or position.get("name"),
                    "status": (entry.get("status") or {}).get("description"),
                    "jersey_number": entry.get("jerseyNumber"),
                })

            if players:
                is_active = roster_type == "active"
                return {
                    "available": True,
                    "players": players,
                    "roster_scope": "active" if is_active else "40Man",
                    "source": (
                        "MLB Stats API · roster activo"
                        if is_active
                        else "MLB Stats API · roster de 40 jugadores (alternativa)"
                    ),
                    "reason": None,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            errors.append(f"{roster_type}: respuesta sin jugadores")
        except Exception as exc:
            errors.append(f"{roster_type}: {type(exc).__name__}")

    return {
        "available": False,
        "players": [],
        "source": "MLB Stats API",
        "reason": "No fue posible recuperar la plantilla activa ni el roster de 40 jugadores.",
        "error_type": "; ".join(errors),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _fetch_previous_game_lineup(team_id, target_game_datetime):
    """Return a prior completed-game batting order for reference, never as confirmed."""
    target_dt = datetime.fromisoformat(str(target_game_datetime).replace("Z", "+00:00"))
    target_day = target_dt.date()
    start_day = target_day - timedelta(days=30)
    response = requests.get(
        f"{MLB_API}/schedule",
        params={
            "sportId": 1,
            "teamId": int(team_id),
            "startDate": start_day.isoformat(),
            "endDate": (target_day - timedelta(days=1)).isoformat(),
        },
        timeout=TIMEOUT_SECONDS,
        headers=HEADERS,
    )
    response.raise_for_status()
    payload = response.json()

    games = []
    for date_entry in payload.get("dates") or []:
        for game in date_entry.get("games") or []:
            status = game.get("status") or {}
            detailed_state = str(status.get("detailedState") or "").lower()
            is_final = (
                status.get("abstractGameState") == "Final"
                or status.get("statusCode") == "F"
                or detailed_state.startswith("final")
            )
            if not is_final:
                continue
            game_pk = _safe_int(game.get("gamePk"))
            if game_pk:
                games.append((str(game.get("officialDate") or date_entry.get("date") or ""), game_pk))

    for game_date, game_pk in sorted(games, reverse=True):
        # Un partido anterior puede no tener feed accesible; no abortar toda
        # la búsqueda por un único 404/HTTPError. Probar el siguiente partido.
        try:
            game_response = requests.get(
                f"{MLB_API}/game/{game_pk}/feed/live",
                timeout=TIMEOUT_SECONDS,
                headers=HEADERS,
            )
            game_response.raise_for_status()
            prior_feed = game_response.json()
        except requests.RequestException:
            continue
        prior_teams = ((prior_feed.get("gameData") or {}).get("teams") or {})
        prior_side = next(
            (
                side for side in ("home", "away")
                if _safe_int((prior_teams.get(side) or {}).get("id")) == int(team_id)
            ),
            None,
        )
        if not prior_side:
            # Fallback team identity from the schedule if the feed lacks gameData.
            prior_game = next(
                (
                    item
                    for date_entry in payload.get("dates") or []
                    for item in date_entry.get("games") or []
                    if _safe_int(item.get("gamePk")) == game_pk
                ),
                {},
            )
            schedule_teams = prior_game.get("teams") or {}
            prior_side = next(
                (
                    side for side in ("home", "away")
                    if _safe_int(((schedule_teams.get(side) or {}).get("team") or {}).get("id")) == int(team_id)
                ),
                None,
            )
        if not prior_side:
            continue

        lineup = extract_confirmed_lineup(prior_feed, prior_side)
        if not lineup:
            # Some completed-game feeds omit the batting order while boxscore has it.
            # A failure for this one game must not prevent trying older games.
            try:
                boxscore_response = requests.get(
                    f"{MLB_API}/game/{game_pk}/boxscore",
                    timeout=TIMEOUT_SECONDS,
                    headers=HEADERS,
                )
                boxscore_response.raise_for_status()
                boxscore = boxscore_response.json()
                boxscore_team = (boxscore.get("teams") or {}).get(prior_side) or {}
                if boxscore_team.get("battingOrder") and boxscore_team.get("players"):
                    prior_feed = {
                        **prior_feed,
                        "liveData": {
                            **(prior_feed.get("liveData") or {}),
                            "boxscore": {
                                **((prior_feed.get("liveData") or {}).get("boxscore") or {}),
                                "teams": {
                                    **(((prior_feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}),
                                    prior_side: boxscore_team,
                                },
                            },
                        },
                    }
                    lineup = extract_confirmed_lineup(prior_feed, prior_side)
            except (requests.RequestException, ValueError):
                # Continue through older completed games instead of returning empty.
                continue

        if lineup:
            return lineup, game_date or None

    return [], None


def get_batter_pitcher_matchups(
    feed,
    home_pitcher,
    away_pitcher,
    home_team_name=None,
    away_team_name=None,
    game_id=None,
):
    """Build direct batter-vs-starter context, retrying lineups via MLB boxscore."""
    lineup_feed = feed
    lineup_sources = {"home": "game_feed", "away": "game_feed"}
    lineup_overrides = {"home": None, "away": None}
    lineup_source_dates = {"home": None, "away": None}
    lineup_lookup_error = None

    # Pregame live feeds can omit boxscore batting orders. Query the dedicated
    # boxscore endpoint once before concluding that lineups are unavailable.
    if game_id and any(not extract_confirmed_lineup(feed, side) for side in ("home", "away")):
        try:
            response = requests.get(
                f"{MLB_API}/game/{int(game_id)}/boxscore",
                timeout=TIMEOUT_SECONDS,
                headers=HEADERS,
            )
            response.raise_for_status()
            boxscore_data = response.json()
            boxscore_teams = boxscore_data.get("teams") or {}
            current_teams = (
                ((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
            )
            merged_teams = dict(current_teams)
            for side in ("home", "away"):
                if not extract_confirmed_lineup(feed, side):
                    fallback_team = boxscore_teams.get(side) or {}
                    if fallback_team.get("battingOrder") and fallback_team.get("players"):
                        merged_teams[side] = fallback_team
                        lineup_sources[side] = "game_boxscore"
            lineup_feed = {
                **feed,
                "liveData": {
                    **(feed.get("liveData") or {}),
                    "boxscore": {
                        **((feed.get("liveData") or {}).get("boxscore") or {}),
                        "teams": merged_teams,
                    },
                },
            }
        except Exception as exc:
            lineup_lookup_error = type(exc).__name__

    # If MLB has not published the target game's batting order, use the most
    # recent completed-game order as a clearly marked reference only. This is
    # not represented as an official or model-generated projected lineup.
    game_data = feed.get("gameData") or {}
    target_datetime = (game_data.get("datetime") or {}).get("dateTime")
    target_teams = game_data.get("teams") or {}
    for side in ("home", "away"):
        if extract_confirmed_lineup(lineup_feed, side):
            continue
        team_id = _safe_int((target_teams.get(side) or {}).get("id"))
        if not team_id or not target_datetime:
            continue
        try:
            previous_lineup, previous_game_date = _fetch_previous_game_lineup(team_id, target_datetime)
            if previous_lineup:
                lineup_overrides[side] = previous_lineup
                lineup_sources[side] = "previous_game_reference"
                lineup_source_dates[side] = previous_game_date
        except Exception as exc:
            if not lineup_lookup_error:
                lineup_lookup_error = type(exc).__name__

    result = {
        "source": "MLB Stats API",
        "scope": "career_vs_pitcher",
        "description": "Historial directo del bateador frente al abridor rival; no equivale al split por mano.",
        "home_team": {},
        "away_team": {},
        "team_rosters": {"home": {}, "away": {}},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Plantillas activas independientes del orden al bate del partido.
    # Un fallo aquí no debe impedir consultar las alineaciones ni el historial BvP.
    target_teams = ((feed.get("gameData") or {}).get("teams") or {})
    for side in ("home", "away"):
        team_id = _safe_int((target_teams.get(side) or {}).get("id"))
        try:
            result["team_rosters"][side] = _fetch_active_roster(team_id)
        except Exception as exc:
            result["team_rosters"][side] = {
                "available": False,
                "players": [],
                "source": "MLB Stats API",
                "reason": "No fue posible consultar la plantilla activa.",
                "error_type": type(exc).__name__,
            }

    for key, side, pitcher, opposing_team_name in (
        ("home_team", "home", away_pitcher, away_team_name),
        ("away_team", "away", home_pitcher, home_team_name),
    ):
        try:
            result[key] = _team_matchup(
                feed=lineup_feed,
                batting_side=side,
                opposing_pitcher=pitcher,
                opposing_team_name=opposing_team_name,
                lineup_source=lineup_sources[side],
                lineup_override=lineup_overrides[side],
                lineup_source_game_date=lineup_source_dates[side],
            )
            if lineup_lookup_error:
                result[key]["lineup_lookup_error"] = lineup_lookup_error
        except Exception as exc:
            result[key] = {
                "available": False,
                "lineup_confirmed": bool(extract_confirmed_lineup(feed, side)),
                "batting_side": side,
                "opposing_pitcher": {
                    "player_id": _safe_int((pitcher or {}).get("pitcher_id") or (pitcher or {}).get("id")),
                    "name": (pitcher or {}).get("pitcher_name") or (pitcher or {}).get("name"),
                    "team": opposing_team_name,
                },
                "hitters": [],
                "lineup_source": lineup_sources[side],
                "reason": "No fue posible consultar el historial directo de bateadores contra el abridor.",
                "error_type": type(exc).__name__,
            }
            if lineup_lookup_error:
                result[key]["lineup_lookup_error"] = lineup_lookup_error

    result["available"] = bool(
        result["home_team"].get("available")
        or result["away_team"].get("available")
    )
    return result
