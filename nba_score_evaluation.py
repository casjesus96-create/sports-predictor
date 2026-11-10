"""Read-only evaluation of NBA pregame team and game-total point projections."""
from __future__ import annotations

import math


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def evaluate_score_projections(rows):
    """Evaluate one latest settled snapshot per game; never modifies predictions."""
    latest_by_event = {}
    for row in rows or []:
        if not isinstance(row, dict) or row.get("result_status") != "SETTLED":
            continue
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        current = latest_by_event.get(event_id)
        created = str(row.get("created_at") or "")
        if current is None or created > str(current.get("created_at") or ""):
            latest_by_event[event_id] = row

    team_errors = []
    total_errors = []
    evaluated = []
    skipped = 0
    for event_id, row in latest_by_event.items():
        features = row.get("features") or {}
        projections = features.get("projections") or {}
        projected_home = _finite(projections.get("home_points"))
        projected_away = _finite(projections.get("away_points"))
        actual_home = _finite(row.get("actual_home_score"))
        actual_away = _finite(row.get("actual_away_score"))
        if None in (projected_home, projected_away, actual_home, actual_away):
            skipped += 1
            continue

        home_error = actual_home - projected_home
        away_error = actual_away - projected_away
        projected_total = projected_home + projected_away
        actual_total = actual_home + actual_away
        total_error = actual_total - projected_total
        team_errors.extend((home_error, away_error))
        total_errors.append(total_error)
        evaluated.append({
            "event_id": event_id,
            "projected_home_points": round(projected_home, 2),
            "projected_away_points": round(projected_away, 2),
            "projected_total_points": round(projected_total, 2),
            "actual_home_points": round(actual_home, 2),
            "actual_away_points": round(actual_away, 2),
            "actual_total_points": round(actual_total, 2),
            "home_error": round(home_error, 2),
            "away_error": round(away_error, 2),
            "total_error": round(total_error, 2),
        })

    def mae(values):
        return round(sum(abs(value) for value in values) / len(values), 3) if values else None

    def rmse(values):
        return round(math.sqrt(sum(value * value for value in values) / len(values)), 3) if values else None

    def bias(values):
        return round(sum(values) / len(values), 3) if values else None

    def within(values, threshold):
        return round(sum(abs(value) <= threshold for value in values) / len(values) * 100, 2) if values else None

    return {
        "sample_games": len(evaluated),
        "skipped_without_valid_projection": skipped,
        "team_score_observations": len(team_errors),
        "team_points_mae": mae(team_errors),
        "team_points_rmse": rmse(team_errors),
        "team_points_bias": bias(team_errors),
        "team_points_within_5_pct": within(team_errors, 5),
        "team_points_within_10_pct": within(team_errors, 10),
        "game_total_mae": mae(total_errors),
        "game_total_rmse": rmse(total_errors),
        "game_total_bias": bias(total_errors),
        "game_total_within_5_pct": within(total_errors, 5),
        "game_total_within_10_pct": within(total_errors, 10),
        "evaluations": evaluated,
        "method": "Una última captura liquidada por partido; error = marcador real menos proyección pregame. Diagnóstico descriptivo, sin reajuste automático.",
    }
