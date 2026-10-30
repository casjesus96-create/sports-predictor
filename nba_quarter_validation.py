"""Historical, read-only validation for immutable pregame NBA quarter projections."""
from __future__ import annotations

from datetime import datetime, timezone
import math

MODEL_VERSION = "NBA-1.1.0"


def _parse_dt(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _mae(pairs):
    errors = [abs(predicted - actual) for predicted, actual in pairs]
    return round(sum(errors) / len(errors), 3) if errors else None


def select_latest_pregame_snapshots(rows):
    """Select one latest valid pregame quarter-projection snapshot per event."""
    latest = {}
    duplicate_count = 0
    for row in rows or []:
        features = row.get("features") or {}
        game = features.get("game") or {}
        projection = (features.get("projections") or {}).get("quarter_points") or {}
        periods = projection.get("periods") or []
        event_id = str(row.get("event_id") or game.get("game_id") or "")
        kickoff = _parse_dt(game.get("kickoff"))
        cutoff = _parse_dt(row.get("data_cutoff") or features.get("analysis_data_cutoff"))
        captured = _parse_dt(row.get("created_at") or features.get("analysis_generated_at"))
        if (not event_id or not projection.get("available") or len(periods) < 4
                or kickoff is None or cutoff is None or captured is None
                or cutoff > kickoff or captured >= kickoff):
            continue
        current = latest.get(event_id)
        if current is None:
            latest[event_id] = row
        else:
            duplicate_count += 1
            current_features = current.get("features") or {}
            current_capture = _parse_dt(current.get("created_at") or current_features.get("analysis_generated_at"))
            if captured > current_capture:
                latest[event_id] = row
    return list(latest.values()), duplicate_count


def evaluate_quarter_projections(rows, actual_quarters_by_game):
    """Compare stored pregame projections with actual Q1-Q4 scores.

    actual_quarters_by_game: {event_id: {home_team_id: [q1..q4], away_team_id: [q1..q4]}}
    No projection or snapshot is changed by this function.
    """
    team_pairs = {period: [] for period in range(1, 5)}
    quarter_combined_pairs = []
    game_total_pairs = []
    home_pairs = []
    away_pairs = []
    evaluated = []
    skipped = {"missing_projection": 0, "missing_actual_quarters": 0, "invalid_or_postgame_cutoff": 0}
    skipped_details = []

    for row in rows or []:
        features = row.get("features") or {}
        game = features.get("game") or {}
        projections = (features.get("projections") or {}).get("quarter_points") or {}
        periods = projections.get("periods") or []
        event_id = str(row.get("event_id") or game.get("game_id") or "")
        if len(periods) < 4 or not projections.get("available"):
            skipped["missing_projection"] += 1
            continue

        kickoff = _parse_dt(game.get("kickoff"))
        cutoff = _parse_dt(row.get("data_cutoff") or features.get("analysis_data_cutoff"))
        captured_at = _parse_dt(row.get("created_at") or features.get("analysis_generated_at"))
        # data_cutoff is the exclusive historical-data boundary, not the wall-clock
        # time at which the snapshot was created. It may equal kickoff because
        # historical queries explicitly include only games strictly before cutoff.
        # The actual snapshot capture must still be strictly before kickoff.
        invalid_reason = None
        if kickoff is None:
            invalid_reason = "missing_kickoff"
        elif cutoff is None:
            invalid_reason = "missing_or_invalid_data_cutoff"
        elif cutoff > kickoff:
            invalid_reason = "data_cutoff_after_kickoff"
        elif captured_at is None:
            invalid_reason = "missing_or_invalid_capture_timestamp"
        elif captured_at >= kickoff:
            invalid_reason = "snapshot_created_at_or_after_kickoff"
        if invalid_reason:
            skipped["invalid_or_postgame_cutoff"] += 1
            skipped_details.append({
                "event_id": event_id,
                "game": game.get("name") or f"{game.get('away', 'Visitante')} @ {game.get('home', 'Local')}",
                "reason": invalid_reason,
                "kickoff": game.get("kickoff"),
                "data_cutoff": row.get("data_cutoff"),
                "analysis_data_cutoff": features.get("analysis_data_cutoff"),
                "created_at": row.get("created_at"),
                "capture_timestamp": row.get("created_at") or features.get("analysis_generated_at"),
            })
            continue
        actual = (actual_quarters_by_game or {}).get(event_id)
        if not actual:
            skipped["missing_actual_quarters"] += 1
            continue
        home_id = str(game.get("home_team_id") or "")
        away_id = str(game.get("away_team_id") or "")
        actual_home = actual.get(home_id)
        actual_away = actual.get(away_id)
        if not isinstance(actual_home, list) or not isinstance(actual_away, list) or len(actual_home) < 4 or len(actual_away) < 4:
            skipped["missing_actual_quarters"] += 1
            continue

        game_evaluated = {"event_id": event_id, "home": game.get("home"), "away": game.get("away"), "quarters": []}
        valid_game = True
        projected_home_total = projected_away_total = 0.0
        actual_home_total = actual_away_total = 0.0
        game_home_pairs = []
        game_away_pairs = []
        game_quarter_pairs = []
        for index in range(4):
            item = periods[index] or {}
            ph = _number(item.get("home_points"))
            pa = _number(item.get("away_points"))
            ah = _number(actual_home[index])
            aa = _number(actual_away[index])
            if None in (ph, pa, ah, aa):
                valid_game = False
                break
            game_home_pairs.append((ph, ah))
            game_away_pairs.append((pa, aa))
            game_quarter_pairs.append((ph + pa, ah + aa))
            projected_home_total += ph
            projected_away_total += pa
            actual_home_total += ah
            actual_away_total += aa
            game_evaluated["quarters"].append({
                "period": index + 1,
                "projected_home": ph, "actual_home": ah,
                "projected_away": pa, "actual_away": aa,
                "home_absolute_error": round(abs(ph - ah), 3),
                "away_absolute_error": round(abs(pa - aa), 3),
                "combined_absolute_error": round(abs((ph + pa) - (ah + aa)), 3),
            })
        if not valid_game:
            skipped["missing_projection"] += 1
            continue

        home_pairs.extend(game_home_pairs)
        away_pairs.extend(game_away_pairs)
        for index, pair in enumerate(game_quarter_pairs, start=1):
            team_pairs[index].extend([game_home_pairs[index - 1], game_away_pairs[index - 1]])
        quarter_combined_pairs.extend(game_quarter_pairs)

        stored_total = _number((features.get("projections") or {}).get("total_points"))
        actual_game_total = _number(row.get("actual_home_score"))
        actual_away_game_total = _number(row.get("actual_away_score"))
        if stored_total is not None and actual_game_total is not None and actual_away_game_total is not None:
            game_total_pairs.append((stored_total, actual_game_total + actual_away_game_total))
        else:
            game_total_pairs.append((projected_home_total + projected_away_total, actual_home_total + actual_away_total))
        game_evaluated["projected_quarter_total"] = round(projected_home_total + projected_away_total, 2)
        game_evaluated["actual_quarter_total"] = round(actual_home_total + actual_away_total, 2)
        evaluated.append(game_evaluated)

    by_quarter = []
    for period in range(1, 5):
        pairs = team_pairs[period]
        by_quarter.append({
            "period": period, "label": f"Q{period}",
            "team_points_mae": _mae(pairs),
            "observations": len(pairs),
        })
    return {
        "success": True,
        "model_version": MODEL_VERSION,
        "method": "MAE calculado únicamente contra marcadores reales Q1-Q4 de ESPN; no modifica NBA-1.1.0 ni los snapshots pregame.",
        "evaluated_games": len(evaluated),
        "team_points_mae": _mae(home_pairs + away_pairs),
        "home_points_mae": _mae(home_pairs),
        "away_points_mae": _mae(away_pairs),
        "quarter_total_mae": _mae(quarter_combined_pairs),
        "game_total_score_mae": _mae(game_total_pairs),
        "by_quarter": by_quarter,
        "skipped": skipped,
        "skipped_details": skipped_details[:50],
        "games": evaluated,
    }
