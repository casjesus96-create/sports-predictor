"""Read-only outcome audit for saved Decision Center evaluations."""
from __future__ import annotations

import math


def build_decision_outcome_audit(evaluations: list[dict], snapshots: list[dict]) -> dict:
    """Compare stored selections and odds with settled outcomes; never mutates data.

    ROI is hypothetical flat-stake ROI in units, not a forecast of future returns.
    Manual evaluations and evaluations without a matching settled snapshot are excluded.
    """
    by_id = {str(row.get("id")): row for row in snapshots if row.get("id") is not None}
    excluded = 0
    rows = []
    for item in evaluations:
        snapshot_id = item.get("prediction_snapshot_id")
        snapshot = by_id.get(str(snapshot_id)) if snapshot_id else None
        if not snapshot or str(snapshot.get("result_status") or "").upper() != "SETTLED":
            excluded += 1
            continue
        sport = str(item.get("sport") or "").upper()
        if sport != "MLB":
            continue
        side = str(item.get("selected_side") or "").lower()
        if side not in {"home", "away"}:
            excluded += 1
            continue
        try:
            home_score = float(snapshot.get("actual_home_score"))
            away_score = float(snapshot.get("actual_away_score"))
            odds = float(item.get("decimal_odds"))
            probability = float(item.get("model_probability"))
            ev = float(item.get("expected_value_percent"))
            if not all(math.isfinite(v) for v in (home_score, away_score, odds, probability, ev)):
                raise ValueError
            if odds <= 1 or not 0 < probability < 1 or home_score == away_score:
                raise ValueError
        except (TypeError, ValueError):
            excluded += 1
            continue
        won = home_score > away_score if side == "home" else away_score > home_score
        rows.append({
            "sport": sport,
            "model_version": item.get("model_version"),
            "classification": str(item.get("classification") or "UNKNOWN"),
            "won": won,
            "expected_value_percent": ev,
            "decimal_odds": odds,
            "profit_units": odds - 1 if won else -1.0,
            "selected_team": item.get("selected_team"),
            "evaluated_at": item.get("evaluated_at"),
        })

    def summarize(items):
        n = len(items)
        wins = sum(1 for x in items if x["won"])
        stake = float(n)
        profit = sum(x["profit_units"] for x in items)
        return {
            "sample_size": n,
            "wins": wins,
            "losses": n - wins,
            "accuracy_percentage": round(wins / n * 100, 2) if n else None,
            "average_expected_value_percent": round(sum(x["expected_value_percent"] for x in items) / n, 2) if n else None,
            "flat_stake_profit_units": round(profit, 4),
            "flat_stake_roi_percentage": round(profit / stake * 100, 2) if n else None,
            "warning": "Muestra descriptiva pequeña; no demuestra rentabilidad futura." if n < 30 else None,
        }

    groups = []
    for classification in sorted({x["classification"] for x in rows}):
        group = summarize([x for x in rows if x["classification"] == classification])
        group["classification"] = classification
        groups.append(group)
    positive_ev = [x for x in rows if x["expected_value_percent"] > 0]
    return {
        "success": True,
        "sport_filter": "MLB",
        "matched_evaluations": len(rows),
        "excluded_evaluations": excluded,
        "overall": summarize(rows),
        "positive_ev_subset": summarize(positive_ev),
        "by_classification": groups,
        "recent_evaluations": rows[-50:],
        "methodology": {
            "matching": "Solo evaluaciones ligadas a un prediction_snapshot_id liquidado; se excluyen evaluaciones manuales/no liquidadas.",
            "outcome": "La selección local gana si actual_home_score > actual_away_score; la visitante gana si ocurre lo contrario.",
            "flat_stake_roi": "Simulación retrospectiva de una unidad por selección: cuota decimal menos 1 si gana, -1 si pierde. No incluye límites, cambios de cuota ni costes.",
            "positive_ev": "Se agrupa por el EV guardado al evaluar; no implica que la probabilidad estuviera calibrada.",
            "immutability": "Solo lectura; no modifica evaluaciones, snapshots ni modelos.",
        },
    }
