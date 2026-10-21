"""Read-only integrity audit for settled prediction snapshots."""
from __future__ import annotations

import math
from collections import Counter

from fastapi import APIRouter, HTTPException, Query

from repository import get_supabase_client

router = APIRouter(prefix="/api/v1/audit", tags=["Auditoría de integridad"])

VALID_SPORTS = {"MLB", "NFL", "NBA", "TENNIS"}


def _normalized_sport(row: dict) -> str:
    raw = str(row.get("league") or row.get("sport") or "").strip().upper()
    return {
        "BASEBALL": "MLB",
        "AMERICAN FOOTBALL": "NFL",
        "FOOTBALL": "NFL",
        "BASKETBALL": "NBA",
    }.get(raw, raw)


def _valid_probability(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0 < number < 1 else None


def _valid_score(value) -> bool:
    try:
        score = float(value)
        return math.isfinite(score) and score >= 0
    except (TypeError, ValueError):
        return False


def audit_settled_row(row: dict) -> list[str]:
    """Return stable issue codes; never mutate or repair the source row."""
    issues = []
    sport = _normalized_sport(row)
    if sport not in VALID_SPORTS:
        issues.append("MISSING_OR_UNKNOWN_SPORT")

    version = row.get("model_version")
    if not isinstance(version, str) or not version.strip() or version.strip().lower() == "unknown":
        issues.append("MISSING_MODEL_VERSION")

    home_p = _valid_probability(row.get("home_probability"))
    away_p = _valid_probability(row.get("away_probability"))
    if home_p is None or away_p is None:
        issues.append("INVALID_PROBABILITIES")
    elif abs((home_p + away_p) - 1.0) > 0.02:
        issues.append("PROBABILITIES_NOT_COMPLEMENTARY")

    home_score = row.get("actual_home_score")
    away_score = row.get("actual_away_score")
    if not _valid_score(home_score) or not _valid_score(away_score):
        issues.append("MISSING_OR_INVALID_FINAL_SCORE")
    elif float(home_score) == float(away_score):
        # NFL regular-season games can legitimately end in a tie. Only accept
        # it as clean when the snapshot explicitly records TIE + PUSH.
        if sport == "NFL":
            if (
                str(row.get("actual_winner") or "").strip().upper() != "TIE"
                or str(row.get("prediction_result") or "").strip().upper() != "PUSH"
            ):
                issues.append("NFL_TIE_SETTLEMENT_MISMATCH")
        else:
            # A tied final score is suspicious for the other supported sports
            # under this snapshot's home/away final-score representation.
            issues.append("TIED_FINAL_SCORE")

    if not row.get("settled_at"):
        issues.append("MISSING_SETTLED_AT")

    return issues


@router.get("/prediction-history")
def audit_prediction_history(limit: int = Query(2000, ge=1, le=5000)):
    """Audit settled snapshots read-only; reports issues without repairing rows."""
    try:
        response = (
            get_supabase_client()
            .table("prediction_snapshots")
            .select(
                "id,event_id,sport,league,model_version,result_status,prediction_result,"
                "home_probability,away_probability,actual_home_score,"
                "actual_away_score,actual_winner,created_at,settled_at"
            )
            .eq("result_status", "SETTLED")
            .order("settled_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = response.data or []
        issue_counts = Counter()
        affected = []
        audited = [(row, audit_settled_row(row)) for row in rows]
        for row, codes in audited:
            if not codes:
                continue
            issue_counts.update(codes)
            if len(affected) < 100:
                affected.append({
                    "id": str(row.get("id") or ""),
                    "event_id": str(row.get("event_id") or ""),
                    "sport": _normalized_sport(row),
                    "model_version": row.get("model_version"),
                    "issues": codes,
                })

        rows_with_issues = sum(1 for _, codes in audited if codes)
        return {
            "success": True,
            "read_only": True,
            "sample_limit": limit,
            "settled_rows_checked": len(rows),
            "rows_with_issues": rows_with_issues,
            "rows_without_issues": len(rows) - rows_with_issues,
            "issue_counts": dict(sorted(issue_counts.items())),
            "affected_records": affected,
            "affected_records_truncated": max(0, rows_with_issues - len(affected)),
        }
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("No se pudo auditar el historial de predicciones")
        raise HTTPException(
            status_code=503,
            detail="No fue posible auditar prediction_snapshots. Comprueba la conexión con Supabase.",
        ) from exc
