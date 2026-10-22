"""Read-only coverage diagnostics for Decision Center outcome tracking."""
from __future__ import annotations


def build_decision_audit_coverage(evaluations: list[dict], snapshots: list[dict]) -> dict:
    """Count where saved MLB evaluations sit in the settlement/linkage pipeline."""
    snapshots_by_id = {
        str(row.get("id")): row
        for row in snapshots
        if row.get("id") is not None
    }
    counts = {
        "total_evaluations": 0,
        "manual_evaluations": 0,
        "linked_evaluations": 0,
        "missing_source_snapshot": 0,
        "source_pending": 0,
        "source_cancelled": 0,
        "source_settled": 0,
        "settled_audit_eligible": 0,
        "settled_missing_selection_side": 0,
        "settled_missing_valid_score": 0,
    }
    by_model = {}

    for item in evaluations:
        if str(item.get("sport") or "").upper() != "MLB":
            continue
        counts["total_evaluations"] += 1
        model = str(item.get("model_version") or "manual_or_unknown")
        group = by_model.setdefault(model, {
            "model_version": model,
            "total_evaluations": 0,
            "manual_evaluations": 0,
            "linked_evaluations": 0,
            "source_pending": 0,
            "source_cancelled": 0,
            "source_settled": 0,
            "settled_audit_eligible": 0,
        })
        group["total_evaluations"] += 1

        snapshot_id = item.get("prediction_snapshot_id")
        if not snapshot_id:
            counts["manual_evaluations"] += 1
            group["manual_evaluations"] += 1
            continue

        counts["linked_evaluations"] += 1
        group["linked_evaluations"] += 1
        source = snapshots_by_id.get(str(snapshot_id))
        if source is None:
            counts["missing_source_snapshot"] += 1
            continue

        status = str(source.get("result_status") or "").upper()
        if status == "PENDING":
            counts["source_pending"] += 1
            group["source_pending"] += 1
        elif status == "CANCELLED":
            counts["source_cancelled"] += 1
            group["source_cancelled"] += 1
        elif status == "SETTLED":
            counts["source_settled"] += 1
            group["source_settled"] += 1
            side = str(item.get("selected_side") or "").lower()
            if side not in {"home", "away"}:
                counts["settled_missing_selection_side"] += 1
                continue
            try:
                home_score = float(source.get("actual_home_score"))
                away_score = float(source.get("actual_away_score"))
                if home_score == away_score:
                    raise ValueError("Tie score is not a valid MLB outcome")
            except (TypeError, ValueError):
                counts["settled_missing_valid_score"] += 1
                continue
            counts["settled_audit_eligible"] += 1
            group["settled_audit_eligible"] += 1
        else:
            counts["missing_source_snapshot"] += 1

    return {
        "success": True,
        "sport_filter": "MLB",
        "coverage": counts,
        "by_model": sorted(by_model.values(), key=lambda row: row["model_version"]),
        "methodology": {
            "manual_evaluations": "No tienen prediction_snapshot_id y no se pueden asociar automáticamente a un resultado.",
            "missing_source_snapshot": "La evaluación contiene un ID, pero no se encontró la fila de origen o su estado no es reconocido.",
            "settled_audit_eligible": "Snapshot liquidado, selección local/visitante identificada y marcador final válido.",
            "immutability": "Solo lectura; no modifica evaluaciones, snapshots, cuotas ni probabilidades.",
        },
    }
