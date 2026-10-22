"""Read-only integrity audit for saved Decision Center probability and EV values."""
from __future__ import annotations

import math


def build_decision_value_integrity_audit(
    evaluations: list[dict],
    snapshots: list[dict],
    *,
    probability_tolerance: float = 1e-6,
    ev_tolerance_percentage_points: float = 0.001,
) -> dict:
    """Compare stored EV math and selected-side probability with immutable snapshots."""
    snapshots_by_id = {
        str(row.get("id")): row
        for row in snapshots
        if row.get("id") is not None
    }
    totals = {
        "evaluations_examined": 0,
        "manual_evaluations": 0,
        "linked_evaluations": 0,
        "missing_snapshot": 0,
        "invalid_values": 0,
        "probability_matches_snapshot": 0,
        "probability_mismatches_snapshot": 0,
        "ev_matches_formula": 0,
        "ev_mismatches_formula": 0,
        "fully_consistent": 0,
    }
    by_model: dict[str, dict] = {}
    recent = []

    for item in evaluations:
        if str(item.get("sport") or "").upper() != "MLB":
            continue
        totals["evaluations_examined"] += 1
        model = str(item.get("model_version") or "manual_or_unknown")
        group = by_model.setdefault(model, {
            "model_version": model,
            "evaluations_examined": 0,
            "manual_evaluations": 0,
            "linked_evaluations": 0,
            "missing_snapshot": 0,
            "invalid_values": 0,
            "probability_matches_snapshot": 0,
            "probability_mismatches_snapshot": 0,
            "ev_matches_formula": 0,
            "ev_mismatches_formula": 0,
            "fully_consistent": 0,
        })
        group["evaluations_examined"] += 1

        snapshot_id = item.get("prediction_snapshot_id")
        if not snapshot_id:
            totals["manual_evaluations"] += 1
            group["manual_evaluations"] += 1
        else:
            totals["linked_evaluations"] += 1
            group["linked_evaluations"] += 1
        snapshot = snapshots_by_id.get(str(snapshot_id)) if snapshot_id else None
        if snapshot_id and snapshot is None:
            totals["missing_snapshot"] += 1
            group["missing_snapshot"] += 1

        try:
            probability = float(item.get("model_probability"))
            odds = float(item.get("decimal_odds"))
            stored_ev = float(item.get("expected_value_percent"))
            if not all(math.isfinite(x) for x in (probability, odds, stored_ev)):
                raise ValueError("Non-finite value")
            if not 0 < probability < 1 or odds <= 1:
                raise ValueError("Probability or odds out of range")
        except (TypeError, ValueError):
            totals["invalid_values"] += 1
            group["invalid_values"] += 1
            recent.append({
                "evaluation_id": item.get("id"),
                "model_version": model,
                "selected_team": item.get("selected_team"),
                "status": "INVALID_STORED_VALUES",
                "stored_model_probability": item.get("model_probability"),
                "snapshot_probability": None,
                "stored_ev_percent": item.get("expected_value_percent"),
                "recalculated_ev_percent": None,
                "ev_matches_formula": False,
                "probability_matches_snapshot": None,
            })
            continue

        # Stored EV is rounded to 3 decimal percentage points by decision_engine.
        recalculated_ev = round((probability * odds - 1.0) * 100.0, 3)
        ev_matches = abs(stored_ev - recalculated_ev) <= ev_tolerance_percentage_points
        if ev_matches:
            totals["ev_matches_formula"] += 1
            group["ev_matches_formula"] += 1
        else:
            totals["ev_mismatches_formula"] += 1
            group["ev_mismatches_formula"] += 1

        snapshot_probability = None
        probability_matches = None
        side = str(item.get("selected_side") or "").lower()
        if snapshot is not None and side in {"home", "away"}:
            try:
                snapshot_probability = float(snapshot.get(
                    "home_probability" if side == "home" else "away_probability"
                ))
                if not math.isfinite(snapshot_probability) or not 0 < snapshot_probability < 1:
                    raise ValueError("Invalid snapshot probability")
                probability_matches = abs(probability - snapshot_probability) <= probability_tolerance
            except (TypeError, ValueError):
                totals["invalid_values"] += 1
                group["invalid_values"] += 1

            if probability_matches is True:
                totals["probability_matches_snapshot"] += 1
                group["probability_matches_snapshot"] += 1
            elif probability_matches is False:
                totals["probability_mismatches_snapshot"] += 1
                group["probability_mismatches_snapshot"] += 1

        fully_consistent = ev_matches and (
            probability_matches is True if snapshot is not None and side in {"home", "away"} else True
        )
        if fully_consistent:
            totals["fully_consistent"] += 1
            group["fully_consistent"] += 1

        if not ev_matches or probability_matches is False:
            status = "EV_AND_PROBABILITY_MISMATCH" if not ev_matches and probability_matches is False else (
                "EV_MISMATCH" if not ev_matches else "SNAPSHOT_PROBABILITY_MISMATCH"
            )
        elif snapshot is not None and side in {"home", "away"} and probability_matches is None:
            status = "SNAPSHOT_PROBABILITY_UNVERIFIABLE"
        elif not snapshot_id:
            status = "MANUAL_EV_CHECKED"
        elif snapshot is None:
            status = "SNAPSHOT_MISSING"
        else:
            status = "CONSISTENT"

        recent.append({
            "evaluation_id": item.get("id"),
            "model_version": model,
            "selected_side": side or None,
            "selected_team": item.get("selected_team"),
            "status": status,
            "stored_model_probability": round(probability, 8),
            "snapshot_probability": round(snapshot_probability, 8) if snapshot_probability is not None else None,
            "probability_difference_percentage_points": (
                round((probability - snapshot_probability) * 100, 6)
                if snapshot_probability is not None else None
            ),
            "decimal_odds": odds,
            "stored_ev_percent": stored_ev,
            "recalculated_ev_percent": recalculated_ev,
            "ev_matches_formula": ev_matches,
            "probability_matches_snapshot": probability_matches,
        })

    return {
        "success": True,
        "sport_filter": "MLB",
        "audit": totals,
        "by_model": sorted(by_model.values(), key=lambda row: row["model_version"]),
        "recent_evaluations": recent[-100:],
        "tolerances": {
            "probability_absolute": probability_tolerance,
            "ev_percentage_points": ev_tolerance_percentage_points,
        },
        "methodology": {
            "expected_value": "EV (%) = (probabilidad guardada × cuota decimal − 1) × 100; se compara con el EV guardado redondeado a 3 decimales.",
            "selected_probability": "En evaluaciones vinculadas, compara la probabilidad guardada con la probabilidad del mismo lado en el snapshot original.",
            "manual_evaluations": "Se comprueba la fórmula EV, pero no existe snapshot para verificar la probabilidad de origen.",
            "immutability": "Solo lectura; no corrige ni modifica evaluaciones, snapshots, probabilidades o resultados.",
            "interpretation": "Una coincidencia matemática no demuestra calibración ni rentabilidad futura.",
        },
    }
