"""Public ESPN scoreboard adapter for ATP/WTA tennis.

This module exposes match facts only. It deliberately does not generate
winner probabilities until historical player data and model validation are
implemented.
"""
from datetime import date, datetime, timedelta, timezone

import requests

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis"
HEADERS = {
    "User-Agent": "Sports-Predictor-Tennis/0.1.0",
    "Accept": "application/json",
}
TIMEOUT = 15
SUPPORTED_LEAGUES = {"ATP", "WTA"}


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("date must use YYYY-MM-DD format")


def _name(competitor):
    athlete = competitor.get("athlete") or {}
    return (
        athlete.get("displayName")
        or athlete.get("fullName")
        or athlete.get("shortName")
        or competitor.get("displayName")
        or competitor.get("name")
    )


def _sets(competitor):
    linescores = competitor.get("linescores") or []
    scores = []
    for line in linescores:
        value = line.get("value")
        if value is None:
            continue
        try:
            score = int(float(value))
        except (TypeError, ValueError):
            continue
        tiebreak = line.get("tiebreak")
        scores.append(f"{score}({tiebreak})" if tiebreak is not None else str(score))
    return scores


def _round_name(competition):
    value = competition.get("round")
    if isinstance(value, dict):
        return value.get("displayName") or value.get("name")
    return value


def _normalize_match(event, competition, league, grouping=None):
    competitors = competition.get("competitors") or []
    player1 = next(
        (item for item in competitors if item.get("homeAway") == "home"),
        competitors[0] if competitors else {},
    )
    player2 = next(
        (item for item in competitors if item.get("homeAway") == "away"),
        competitors[1] if len(competitors) > 1 else {},
    )
    status = (competition.get("status") or {}).get("type") or {}
    date_value = competition.get("date") or competition.get("startDate") or event.get("date")
    tournament = event.get("name") or event.get("shortName") or "Tournament"
    match_type = (
        (competition.get("type") or {}).get("text")
        or (grouping or {}).get("displayName")
        or "Singles"
    )
    return {
        "match_id": str(competition.get("id") or ""),
        "event_id": str(event.get("id") or ""),
        "league": league,
        "tournament": tournament,
        "match_type": match_type,
        "round": _round_name(competition),
        "start_time": date_value,
        "status": status.get("state") or "unknown",
        "status_detail": status.get("description") or status.get("detail") or status.get("shortDetail"),
        "completed": bool(status.get("completed")),
        "player1": {
            "id": str(player1.get("id") or ""),
            "name": _name(player1),
            "country": ((player1.get("athlete") or {}).get("flag") or {}).get("alt"),
            "winner": player1.get("winner"),
            "sets": _sets(player1),
        },
        "player2": {
            "id": str(player2.get("id") or ""),
            "name": _name(player2),
            "country": ((player2.get("athlete") or {}).get("flag") or {}).get("alt"),
            "winner": player2.get("winner"),
            "sets": _sets(player2),
        },
        "venue": (competition.get("venue") or {}).get("fullName")
        or (competition.get("venue") or {}).get("court"),
        "data_source": "ESPN scoreboard",
    }


def normalize_scoreboard(payload, league):
    """Flatten ESPN event/grouping/competition structures to match rows."""
    matches = []
    seen = set()
    for event in payload.get("events") or []:
        groupings = event.get("groupings") or []
        for grouping_entry in groupings:
            grouping = grouping_entry.get("grouping") or {}
            grouping_name = str(grouping.get("displayName") or "").casefold()
            competitions = grouping_entry.get("competitions") or []
            for competition in competitions:
                match_type = (
                    (competition.get("type") or {}).get("text")
                    or grouping.get("displayName")
                    or ""
                ).casefold()
                # Tennis MVP starts with singles; doubles are intentionally excluded.
                if "single" not in match_type and "single" not in grouping_name:
                    continue
                match = _normalize_match(event, competition, league, grouping)
                if match["match_id"] and match["match_id"] not in seen:
                    seen.add(match["match_id"])
                    matches.append(match)

        # Some ESPN responses expose competitions directly on an event.
        for competition in event.get("competitions") or []:
            match_type = ((competition.get("type") or {}).get("text") or "").casefold()
            if "single" not in match_type:
                continue
            match = _normalize_match(event, competition, league)
            if match["match_id"] and match["match_id"] not in seen:
                seen.add(match["match_id"])
                matches.append(match)

    matches.sort(key=lambda row: (row.get("start_time") or "", row["tournament"], row["match_id"]))
    return matches


def get_matches(league="ATP", days=14, start_date=None):
    league = str(league or "ATP").strip().upper()
    if league not in SUPPORTED_LEAGUES:
        raise ValueError("league must be ATP or WTA")
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError("days must be an integer")
    if not 1 <= days <= 30:
        raise ValueError("days must be between 1 and 30")

    start = _parse_date(start_date) if start_date else datetime.now(timezone.utc).date()
    end = start + timedelta(days=days - 1)
    date_range = f"{start:%Y%m%d}-{end:%Y%m%d}"
    response = requests.get(
        f"{BASE_URL}/{league.lower()}/scoreboard",
        params={"dates": date_range, "limit": 1000},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    matches = normalize_scoreboard(payload, league)
    # Filter locally as ESPN can include other matches from a tournament.
    filtered = []
    for match in matches:
        raw = match.get("start_time")
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            match_date = parsed.astimezone(timezone.utc).date()
        except (TypeError, ValueError):
            continue
        if start <= match_date <= end:
            filtered.append(match)
    return filtered
