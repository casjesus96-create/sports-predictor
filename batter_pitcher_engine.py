"""Batter-versus-pitcher pregame context using MLB Stats API.

Only confirmed batting orders are used. This module is descriptive and does not
change the official MLB 2.0.0-matchup win probabilities.
"""
from datetime import datetime, timezone

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


def _team_matchup(feed, batting_side, opposing_pitcher, opposing_team_name):
    lineup = extract_confirmed_lineup(feed, batting_side)
    pitcher_id = _safe_int((opposing_pitcher or {}).get("pitcher_id") or (opposing_pitcher or {}).get("id"))
    pitcher_name = (opposing_pitcher or {}).get("pitcher_name") or (opposing_pitcher or {}).get("name")

    base = {
        "available": False,
        "lineup_confirmed": bool(lineup),
        "batting_side": batting_side,
        "opposing_pitcher": {
            "player_id": pitcher_id,
            "name": pitcher_name,
            "team": opposing_team_name,
        },
        "hitters": [],
    }

    if not lineup:
        base["reason"] = "MLB todavía no ha publicado una alineación confirmada para este equipo."
        return base

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
    base["reason"] = None if base["available"] else "Alineación confirmada, pero no hay historial directo suficiente disponible para los bateadores."
    base["scope"] = "career_vs_pitcher"
    base["generated_at"] = datetime.now(timezone.utc).isoformat()
    return base


def get_batter_pitcher_matchups(feed, home_pitcher, away_pitcher, home_team_name=None, away_team_name=None):
    """Build home hitters vs away starter and away hitters vs home starter."""
    result = {
        "source": "MLB Stats API",
        "scope": "career_vs_pitcher",
        "description": "Historial directo del bateador frente al abridor rival; no equivale al split por mano.",
        "home_team": {},
        "away_team": {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    for key, side, pitcher, opposing_team_name in (
        ("home_team", "home", away_pitcher, away_team_name),
        ("away_team", "away", home_pitcher, home_team_name),
    ):
        try:
            result[key] = _team_matchup(
                feed=feed,
                batting_side=side,
                opposing_pitcher=pitcher,
                opposing_team_name=opposing_team_name,
            )
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
                "reason": "No fue posible consultar el historial directo de bateadores contra el abridor.",
                "error_type": type(exc).__name__,
            }

    result["available"] = bool(
        result["home_team"].get("available")
        or result["away_team"].get("available")
    )
    return result
