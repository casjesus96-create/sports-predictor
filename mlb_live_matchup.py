"""Summarize batter results against each pitcher from the current MLB game's play-by-play."""
from __future__ import annotations

_NON_AT_BAT_EVENTS = {
    "walk", "intentional_walk", "hit_by_pitch", "sac_fly", "sac_bunt",
    "sacrifice_fly", "sacrifice_bunt", "catcher_interference", "interference",
}
_HIT_EVENTS = {"single", "double", "triple", "home_run"}


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_live_pitcher_matchup_stats(all_plays):
    """Return current-game hit/AB totals grouped by batter and pitcher."""
    totals = {}
    for play in all_plays if isinstance(all_plays, list) else []:
        if not isinstance(play, dict):
            continue
        matchup = play.get("matchup") or {}
        batter = matchup.get("batter") or {}
        pitcher = matchup.get("pitcher") or {}
        batter_id = _int(batter.get("id"))
        pitcher_id = _int(pitcher.get("id"))
        result = play.get("result") or {}
        event_type = str(result.get("eventType") or "").strip().lower().replace(" ", "_")
        if not batter_id or not pitcher_id or not event_type:
            continue
        key = (batter_id, pitcher_id)
        entry = totals.setdefault(key, {
            "batter_id": batter_id, "pitcher_id": pitcher_id,
            "pitcher_name": pitcher.get("fullName") or pitcher.get("name") or f"Pitcher {pitcher_id}",
            "hits": 0, "at_bats": 0,
        })
        if event_type in _HIT_EVENTS:
            entry["hits"] += 1
        is_at_bat = result.get("isAtBat")
        if isinstance(is_at_bat, bool):
            entry["at_bats"] += int(is_at_bat)
        elif event_type not in _NON_AT_BAT_EVENTS:
            entry["at_bats"] += 1

    by_batter = {}
    for entry in totals.values():
        at_bats = entry["at_bats"]
        entry["avg"] = round(entry["hits"] / at_bats, 3) if at_bats else None
        by_batter.setdefault(entry["batter_id"], []).append({
            key: value for key, value in entry.items() if key != "batter_id"
        })
    for entries in by_batter.values():
        entries.sort(key=lambda item: (item["pitcher_name"].casefold(), item["pitcher_id"]))
    return by_batter
