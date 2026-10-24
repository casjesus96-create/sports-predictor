"""Persistent football prediction snapshots and idempotent official result settlement."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from repository import get_supabase_client
from football_model import MODEL_VERSION

logger = logging.getLogger(__name__)


def _outcome(home: int, away: int) -> str:
    return "HOME" if home > away else "AWAY" if home < away else "DRAW"


def record_pregame_snapshot(match: dict[str, Any], competition: str, prediction: dict[str, Any]) -> bool:
    """Insert once per provider match/model; never overwrite the original forecast."""
    if not prediction.get("available") or not isinstance(match.get("id"), int):
        return False
    home = (match.get("homeTeam") or {}).get("name")
    away = (match.get("awayTeam") or {}).get("name")
    probs = prediction.get("probabilities") or {}
    if not home or not away or not all(isinstance(probs.get(k), (int, float)) for k in ("home", "draw", "away")):
        return False
    payload = {
        "provider_match_id": match["id"],
        "competition_code": competition.upper(),
        "kickoff_at": match.get("utcDate"),
        "home_team": home,
        "away_team": away,
        "model_version": prediction.get("model_version"),
        "home_probability": probs["home"],
        "draw_probability": probs["draw"],
        "away_probability": probs["away"],
        "expected_goals": prediction.get("expected_goals") or {},
        "prediction_payload": prediction,
        "data_cutoff_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        get_supabase_client().table("football_prediction_snapshots").upsert(
            payload, on_conflict="provider_match_id,model_version", ignore_duplicates=True
        ).execute()
        return True
    except Exception:
        logger.exception("Could not persist football pregame snapshot for match %s", match.get("id"))
        return False


def settle_official_result(match: dict[str, Any], competition: str) -> bool:
    """Settle only official completed results with numeric full-time scores."""
    status = str(match.get("status") or "").upper()
    if status not in {"FINISHED", "AWARDED"} or not isinstance(match.get("id"), int):
        return False
    score = (match.get("score") or {}).get("fullTime") or {}
    home_score, away_score = score.get("home"), score.get("away")
    if not (isinstance(home_score, int) and isinstance(away_score, int) and home_score >= 0 and away_score >= 0):
        return False
    try:
        client = get_supabase_client()
        existing = client.table("football_prediction_snapshots").select("id,result_status").eq(
            "provider_match_id", match["id"]
        ).eq("model_version", MODEL_VERSION).eq("result_status", "PENDING").execute()
        if not (existing.data or []):
            return False
        client.table("football_prediction_snapshots").update({
            "result_status": "SETTLED",
            "actual_home_score": home_score,
            "actual_away_score": away_score,
            "actual_outcome": _outcome(home_score, away_score),
            "result_source": "football-data.org",
            "settled_at": datetime.now(timezone.utc).isoformat(),
        }).eq("provider_match_id", match["id"]).eq(
            "model_version", MODEL_VERSION
        ).execute()
        return True
    except Exception:
        logger.exception("Could not settle football result for match %s", match.get("id"))
        return False
