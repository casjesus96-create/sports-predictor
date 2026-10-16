"""Persistence and settlement helpers for tennis prediction snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from repository import get_supabase_client


TABLE = "tennis_prediction_snapshots"


def save_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert once per match/model; never overwrite original probabilities."""
    client = get_supabase_client()
    existing = (
        client.table(TABLE)
        .select("*")
        .eq("league", payload["league"])
        .eq("match_id", payload["match_id"])
        .eq("model_version", payload["model_version"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return {"saved": False, "already_exists": True, "snapshot": existing.data[0]}

    response = client.table(TABLE).insert(payload).execute()
    if response.data:
        return {"saved": True, "already_exists": False, "snapshot": response.data[0]}

    raise RuntimeError("Supabase no devolvió el snapshot de tenis insertado.")


def get_pending_snapshot(match_id: str, league: str) -> dict[str, Any] | None:
    client = get_supabase_client()
    response = (
        client.table(TABLE)
        .select("*")
        .eq("match_id", str(match_id))
        .eq("league", league.upper())
        .eq("result_status", "PENDING")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def get_latest_snapshot(match_id: str, league: str) -> dict[str, Any] | None:
    client = get_supabase_client()
    response = (
        client.table(TABLE)
        .select("*")
        .eq("match_id", str(match_id))
        .eq("league", league.upper())
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def settle_snapshot(
    snapshot: dict[str, Any],
    winner_id: str | None,
    winner_name: str,
) -> dict[str, Any]:
    """Settle one pending snapshot exactly once using a verified final winner."""
    p1 = snapshot.get("player1_probability")
    p2 = snapshot.get("player2_probability")
    if p1 is None or p2 is None:
        raise ValueError("El snapshot no contiene las probabilidades originales.")
    p1 = float(p1)
    p2 = float(p2)

    p1_id = str(snapshot.get("player1_id") or "")
    p2_id = str(snapshot.get("player2_id") or "")
    actual_id = str(winner_id or "")
    if actual_id and p1_id and actual_id == p1_id:
        actual_player1_won = True
    elif actual_id and p2_id and actual_id == p2_id:
        actual_player1_won = False
    else:
        # ESPN ids may be absent or inconsistent across feeds; use strict
        # normalized names only as a fallback, never fuzzy matching.
        from tennis_prediction import normalize_player_name
        actual_key = normalize_player_name(winner_name)
        p1_key = normalize_player_name(snapshot.get("player1_name"))
        p2_key = normalize_player_name(snapshot.get("player2_name"))
        if actual_key and actual_key == p1_key:
            actual_player1_won = True
        elif actual_key and actual_key == p2_key:
            actual_player1_won = False
        else:
            raise ValueError("El ganador oficial no coincide con los jugadores del snapshot.")

    predicted_player1_wins = p1 >= p2
    result_status = "CORRECT" if predicted_player1_wins == actual_player1_won else "INCORRECT"
    client = get_supabase_client()
    response = (
        client.table(TABLE)
        .update({
            "result_status": result_status,
            "actual_winner_id": actual_id or None,
            "actual_winner_name": winner_name,
            "settled_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", snapshot["id"])
        .eq("result_status", "PENDING")
        .execute()
    )
    if response.data:
        return {"settled": True, "snapshot": response.data[0]}

    # Another request may have settled it between the read and update.
    latest = (
        client.table(TABLE)
        .select("*")
        .eq("id", snapshot["id"])
        .limit(1)
        .execute()
    )
    if latest.data:
        return {"settled": False, "already_settled": True, "snapshot": latest.data[0]}
    raise RuntimeError("No fue posible confirmar la liquidación del pronóstico.")


def performance_summary(league: str | None = None) -> dict[str, Any]:
    """Calculate accuracy, Brier score, and log loss from settled snapshots."""
    client = get_supabase_client()
    query = client.table(TABLE).select("*").in_("result_status", ["CORRECT", "INCORRECT"])
    if league:
        query = query.eq("league", league.upper())
    response = query.execute()
    rows = response.data or []

    count = len(rows)
    if not count:
        return {
            "success": True,
            "model": "Tennis Elo general",
            "model_status": "candidate_not_activated",
            "matches_settled": 0,
            "accuracy": None,
            "brier_score": None,
            "log_loss": None,
            "message": "Todavía no hay pronósticos de tenis liquidados para evaluar.",
        }

    brier_sum = 0.0
    log_loss_sum = 0.0
    correct = 0
    import math
    from tennis_prediction import normalize_player_name
    for row in rows:
        p1 = float(row["player1_probability"])
        p2 = float(row["player2_probability"])
        winner_key = normalize_player_name(row.get("actual_winner_name"))
        p1_key = normalize_player_name(row.get("player1_name"))
        actual_p1 = winner_key == p1_key
        actual = 1.0 if actual_p1 else 0.0
        brier_sum += (p1 - actual) ** 2
        chosen_p1 = p1 >= p2
        correct += int(chosen_p1 == actual_p1)
        chosen_probability = p1 if actual_p1 else p2
        log_loss_sum -= math.log(min(1.0 - 1e-15, max(1e-15, chosen_probability)))

    return {
        "success": True,
        "model": "Tennis Elo general",
        "model_version": rows[0].get("model_version"),
        "model_status": "candidate_not_activated",
        "league": league.upper() if league else "ATP+WTA",
        "matches_settled": count,
        "correct": correct,
        "incorrect": count - correct,
        "accuracy": round(correct / count, 4),
        "brier_score": round(brier_sum / count, 6),
        "log_loss": round(log_loss_sum / count, 6),
        "note": "Métricas descriptivas; no autorizan por sí solas cambios automáticos de parámetros.",
    }
