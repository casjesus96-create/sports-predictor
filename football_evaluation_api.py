"""Read-only evaluation of settled football 1X2 prediction snapshots."""
from __future__ import annotations

import math
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from repository import get_supabase_client

router = APIRouter(prefix="/api/v1/football", tags=["Football evaluation"])


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def evaluate_rows(rows: list[dict]) -> dict:
    """Compute multiclass Brier, log loss, accuracy and outcome breakdown."""
    valid = []
    skipped = 0
    for row in rows:
        probs = [_number(row.get(k)) for k in (
            "home_probability", "draw_probability", "away_probability"
        )]
        hs, aws = _number(row.get("actual_home_score")), _number(row.get("actual_away_score"))
        if (any(p is None or p < 0 or p > 1 for p in probs)
                or abs(sum(probs) - 1.0) > 0.02
                or hs is None or aws is None or hs < 0 or aws < 0):
            skipped += 1
            continue
        total = sum(probs)
        probs = [p / total for p in probs]
        outcome = "home" if hs > aws else "away" if hs < aws else "draw"
        actual = {"home": 0, "draw": 1, "away": 2}[outcome]
        valid.append((row, probs, outcome, actual))

    if not valid:
        return {"sample_size": 0, "skipped_rows": skipped, "metrics": None,
                "by_outcome": {}, "by_competition": {}, "calibration": [],
                "status": "insufficient_data"}

    eps = 1e-15
    brier = sum(sum((p - (i == actual)) ** 2 for i, p in enumerate(probs))
                for _, probs, _, actual in valid) / len(valid)
    log_loss = -sum(math.log(max(eps, probs[actual])) for _, probs, _, actual in valid) / len(valid)
    correct = sum(max(range(3), key=lambda i: probs[i]) == actual
                  for _, probs, _, actual in valid)

    def group_summary(items):
        n = len(items)
        return {
            "sample_size": n,
            "accuracy": round(sum(max(range(3), key=lambda i: p[i]) == a for _, p, _, a in items) / n, 6),
            "brier_score": round(sum(sum((p[i] - (i == a)) ** 2 for i in range(3)) for _, p, _, a in items) / n, 6),
            "log_loss": round(-sum(math.log(max(eps, p[a])) for _, p, _, a in items) / n, 6),
        }

    outcomes = {}
    for outcome in ("home", "draw", "away"):
        items = [item for item in valid if item[2] == outcome]
        outcomes[outcome] = {
            "actual_count": len(items),
            "mean_predicted_probability": round(sum(item[1][{"home":0,"draw":1,"away":2}[outcome]] for item in valid) / len(valid), 6),
            "observed_frequency": round(len(items) / len(valid), 6),
        }

    competitions = defaultdict(list)
    for item in valid:
        competitions[str(item[0].get("competition_code") or "UNKNOWN")].append(item)

    calibration = []
    for index, label in enumerate(("home", "draw", "away")):
        calibration.append({
            "outcome": label,
            "mean_predicted_probability": outcomes[label]["mean_predicted_probability"],
            "observed_frequency": outcomes[label]["observed_frequency"],
            "absolute_gap": round(abs(outcomes[label]["mean_predicted_probability"] - outcomes[label]["observed_frequency"]), 6),
        })

    return {
        "sample_size": len(valid),
        "skipped_rows": skipped,
        "metrics": {
            "accuracy": round(correct / len(valid), 6),
            "brier_score": round(brier, 6),
            "log_loss": round(log_loss, 6),
        },
        "by_outcome": outcomes,
        "by_competition": {key: group_summary(items) for key, items in sorted(competitions.items())},
        "calibration": calibration,
        "status": "insufficient_data" if len(valid) < 30 else "descriptive_only",
        "minimum_sample_guidance": "Menos de 30 partidos: evidencia insuficiente; incluso con 30, interpretar con cautela.",
    }


@router.get("/evaluation")
def football_evaluation(
    competition: str | None = Query(None, min_length=2, max_length=8),
    model_version: str | None = Query(None, min_length=3, max_length=80),
    limit: int = Query(2000, ge=1, le=5000),
):
    """Read settled football snapshots only; does not change predictions."""
    try:
        query = (
            get_supabase_client().table("football_prediction_snapshots")
            .select("provider_match_id,competition_code,model_version,kickoff_at,home_probability,draw_probability,away_probability,actual_home_score,actual_away_score,actual_outcome,result_status,settled_at")
            .eq("result_status", "SETTLED")
            .order("kickoff_at", desc=True)
            .limit(limit)
        )
        if competition:
            query = query.eq("competition_code", competition.upper())
        if model_version:
            query = query.eq("model_version", model_version)
        rows = query.execute().data or []
        result = evaluate_rows(rows)
        result.update({
            "success": True,
            "read_only": True,
            "model_versions": sorted({str(r.get("model_version") or "UNKNOWN") for r in rows}),
            "competition_filter": competition.upper() if competition else None,
            "model_version_filter": model_version,
            "source": "football_prediction_snapshots",
        })
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="No fue posible leer el historial de fútbol. Verifica que la tabla football_prediction_snapshots esté creada y accesible.",
        ) from exc
