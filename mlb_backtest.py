"""Evaluation helpers for immutable, official-model MLB pregame snapshots.

This evaluates predictions actually saved before each game, not a retrospective
reconstruction from end-of-season statistics. That distinction avoids look-ahead
leakage and makes the sample size explicit.
"""
from datetime import datetime, timezone
import math

OFFICIAL_MLB_MODEL = "2.0.0-matchup"


def _finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def snapshot_pregame_eligible(row, model_version=OFFICIAL_MLB_MODEL):
    """True only for settled official-model snapshots recorded before game time."""
    if not isinstance(row, dict):
        return False
    if row.get("model_version") != model_version:
        return False
    if str(row.get("result_status") or "").upper() != "SETTLED":
        return False
    features = row.get("features") or {}
    game = features.get("game") or {}
    game_start = _parse_datetime(game.get("date"))
    cutoff = _parse_datetime(row.get("data_cutoff") or row.get("created_at"))
    return bool(game_start and cutoff and cutoff < game_start)


def _run_projection(row):
    features = row.get("features") or {}
    factors = features.get("factors") or {}
    projection = factors.get("run_projection") or {}
    if not isinstance(projection, dict) or projection.get("available") is not True:
        return None
    home = _finite_number((projection.get("home") or {}).get("expected_runs"))
    away = _finite_number((projection.get("away") or {}).get("expected_runs"))
    tie_probability = _finite_number(projection.get("probability_tied_after_nine"))
    if home is None or away is None or home < 0 or away < 0:
        return None
    if tie_probability is not None and not 0 <= tie_probability <= 1:
        tie_probability = None
    return {"home": home, "away": away, "tie_probability": tie_probability}


def snapshot_has_valid_run_projection(row):
    """Whether the canonical stored location contains a usable run projection."""
    return _run_projection(row) is not None


def snapshot_needs_tie_observation(row):
    """Avoid MLB feed requests unless a valid pregame projection needs tie scoring."""
    if not snapshot_pregame_eligible(row):
        return False
    projection = _run_projection(row)
    if projection is None or projection["tie_probability"] is None:
        return False
    home_actual = _finite_number(row.get("actual_home_score"))
    away_actual = _finite_number(row.get("actual_away_score"))
    return (
        home_actual is not None and away_actual is not None
        and home_actual >= 0 and away_actual >= 0
        and bool(str(row.get("event_id") or "").strip())
    )


def diagnose_projection_storage(rows):
    """Summarize where saved projections live without exposing full feature payloads."""
    rows = rows or []
    counts = {
        "queried_snapshots": len(rows),
        "official_settled_pregame_snapshots": 0,
        "valid_run_projection_at_canonical_path": 0,
        "missing_or_invalid_run_projection_at_canonical_path": 0,
        "projection_at_alternate_top_level_path": 0,
        "projection_components_at_factors_top_level": 0,
        "valid_tie_probability": 0,
        "status_counts": {},
    }
    examples = []
    for row in rows:
        status = str(row.get("result_status") or "UNKNOWN").upper()
        counts["status_counts"][status] = counts["status_counts"].get(status, 0) + 1
        if snapshot_pregame_eligible(row):
            counts["official_settled_pregame_snapshots"] += 1
        projection = _run_projection(row)
        if projection is not None:
            counts["valid_run_projection_at_canonical_path"] += 1
            if projection["tie_probability"] is not None:
                counts["valid_tie_probability"] += 1
        else:
            counts["missing_or_invalid_run_projection_at_canonical_path"] += 1

        features = row.get("features") if isinstance(row, dict) else {}
        features = features if isinstance(features, dict) else {}
        factors = features.get("factors")
        factors = factors if isinstance(factors, dict) else {}
        alternate = features.get("run_projection")
        if isinstance(alternate, dict):
            counts["projection_at_alternate_top_level_path"] += 1
        if any(key in factors for key in ("home_expected_runs", "away_expected_runs", "expected_runs")):
            counts["projection_components_at_factors_top_level"] += 1

        if projection is None and len(examples) < 5:
            game = features.get("game")
            game = game if isinstance(game, dict) else {}
            examples.append({
                "id": row.get("id"),
                "event_id": row.get("event_id"),
                "created_at": row.get("created_at"),
                "game_date": game.get("date"),
                "feature_keys": sorted(features.keys()),
                "factor_keys": sorted(factors.keys()),
                "alternate_run_projection_present": isinstance(alternate, dict),
            })
    counts["missing_examples"] = examples
    return counts


def diagnose_pitcher_strikeout_storage(rows):
    """Report whether saved snapshots contain usable pregame starter-K projections.

    This is a storage-coverage audit only. Final pitcher strikeouts are not
    stored in prediction_snapshots settlement fields, so this function never
    fabricates actuals or reports K accuracy.
    """
    result = {
        "queried_snapshots": len(rows or []),
        "official_settled_pregame_snapshots": 0,
        "snapshots_with_projection": 0,
        "home_pitcher_projection_count": 0,
        "away_pitcher_projection_count": 0,
        "missing_or_invalid_projection_count": 0,
        "home_pitcher_id_present": 0,
        "away_pitcher_id_present": 0,
        "actual_strikeouts_available_in_snapshot": 0,
        "evaluation_status": "not_evaluable_actual_pitcher_strikeouts_not_stored",
    }
    for row in rows or []:
        if snapshot_pregame_eligible(row):
            result["official_settled_pregame_snapshots"] += 1
        features = row.get("features") or {}
        factors = features.get("factors") or {}
        projection = factors.get("pitcher_strikeout_projection") or {}
        probable = factors.get("probable_pitchers") or {}
        valid_sides = 0
        for side in ("home", "away"):
            pitcher_key = f"{side}_pitcher" if side in ("home", "away") else side
            pitcher_projection = projection.get(pitcher_key) or {}
            expected = _finite_number(pitcher_projection.get("expected_strikeouts"))
            if pitcher_projection.get("available") is True and expected is not None and expected >= 0:
                valid_sides += 1
                result[f"{side}_pitcher_projection_count"] += 1
            pitcher = probable.get(side) or {}
            if pitcher.get("pitcher_id") or pitcher.get("id"):
                result[f"{side}_pitcher_id_present"] += 1
        if valid_sides:
            result["snapshots_with_projection"] += 1
        else:
            result["missing_or_invalid_projection_count"] += 1
        # The current settlement schema stores team scores, not individual
        # pitcher strikeout totals. Keep this explicit until a verified source
        # and immutable pitcher/game identity are available.
    return result


def extract_pitcher_strikeout_observations(feed, features):
    """Extract final starter strikeouts only when the observed starter matches
    the pitcher identity saved in the original pregame snapshot.
    """
    if not isinstance(feed, dict):
        return {"status": "feed_unavailable", "source": "MLB StatsAPI boxscore"}
    game_status = ((feed.get("gameData") or {}).get("status") or {})
    if str(game_status.get("abstractGameState") or "").lower() != "final":
        return {"status": "game_not_final", "source": "MLB StatsAPI boxscore"}

    factors = (features or {}).get("factors") or {}
    probable = factors.get("probable_pitchers") or {}
    boxscore_teams = ((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
    observations = {}
    for side in ("home", "away"):
        saved_pitcher = probable.get(side) or {}
        expected_id = saved_pitcher.get("pitcher_id") or saved_pitcher.get("id")
        team_box = boxscore_teams.get(side) or {}
        pitcher_ids = team_box.get("pitchers") or []
        if not expected_id or not pitcher_ids:
            observations[side] = {"status": "missing_pitcher_identity"}
            continue
        starter_id = pitcher_ids[0]
        if str(starter_id) != str(expected_id):
            observations[side] = {
                "status": "starter_mismatch",
                "expected_pitcher_id": str(expected_id),
                "observed_starter_id": str(starter_id),
            }
            continue
        player = (team_box.get("players") or {}).get(f"ID{starter_id}") or {}
        pitching = ((player.get("stats") or {}).get("pitching") or {})
        strikeouts = _finite_number(pitching.get("strikeOuts"))
        if strikeouts is None or strikeouts < 0 or not strikeouts.is_integer():
            observations[side] = {
                "status": "missing_or_invalid_boxscore_strikeouts",
                "pitcher_id": str(starter_id),
            }
            continue
        observations[side] = {
            "status": "matched",
            "pitcher_id": str(starter_id),
            "strikeouts": int(strikeouts),
        }

    matched = sum(1 for value in observations.values() if value.get("status") == "matched")
    return {
        "status": "captured" if matched else "no_verified_starter_observations",
        "source": "MLB StatsAPI liveData.boxscore.teams",
        "observations": observations,
    }


def calculate_mlb_backtest_metrics(rows, tie_observations=None):
    """Calculate score errors and tie-probability Brier score from saved snapshots.

    tie_observations maps event_id to True/False when the official MLB feed
    provides complete inning-by-inning data through nine innings. Missing values
    are intentionally excluded rather than guessed.
    """
    tie_observations = tie_observations or {}
    eligible = []
    exclusions = {
        "not_official_settled_pregame_snapshot": 0,
        "missing_or_invalid_run_projection": 0,
        "missing_or_invalid_final_score": 0,
    }

    for row in rows or []:
        if not snapshot_pregame_eligible(row):
            exclusions["not_official_settled_pregame_snapshot"] += 1
            continue
        projection = _run_projection(row)
        if projection is None:
            exclusions["missing_or_invalid_run_projection"] += 1
            continue
        home_actual = _finite_number(row.get("actual_home_score"))
        away_actual = _finite_number(row.get("actual_away_score"))
        if (
            home_actual is None or away_actual is None
            or home_actual < 0 or away_actual < 0
        ):
            exclusions["missing_or_invalid_final_score"] += 1
            continue
        eligible.append({
            "event_id": str(row.get("event_id") or ""),
            "home_expected": projection["home"],
            "away_expected": projection["away"],
            "tie_probability": projection["tie_probability"],
            "home_actual": home_actual,
            "away_actual": away_actual,
        })

    def error_metrics(errors):
        if not errors:
            return {"mae": None, "rmse": None}
        return {
            "mae": round(sum(abs(value) for value in errors) / len(errors), 6),
            "rmse": round(math.sqrt(sum(value * value for value in errors) / len(errors)), 6),
        }

    home_errors = [item["home_expected"] - item["home_actual"] for item in eligible]
    away_errors = [item["away_expected"] - item["away_actual"] for item in eligible]
    team_errors = home_errors + away_errors
    total_errors = [
        item["home_expected"] + item["away_expected"]
        - item["home_actual"] - item["away_actual"]
        for item in eligible
    ]

    tie_samples = []
    for item in eligible:
        observed = tie_observations.get(item["event_id"])
        probability = item["tie_probability"]
        if isinstance(observed, bool) and probability is not None:
            tie_samples.append((probability, 1.0 if observed else 0.0))

    tie_brier = (
        sum((probability - observed) ** 2 for probability, observed in tie_samples)
        / len(tie_samples)
        if tie_samples else None
    )

    return {
        "success": True,
        "evaluation_type": "saved_pregame_snapshots",
        "model_version": OFFICIAL_MLB_MODEL,
        "sample_size": len(eligible),
        "team_run_observations": len(team_errors),
        "run_metrics": {
            "home_runs": error_metrics(home_errors),
            "away_runs": error_metrics(away_errors),
            "per_team": error_metrics(team_errors),
            "total_runs": error_metrics(total_errors),
        },
        "tie_after_nine": {
            "sample_size": len(tie_samples),
            "brier_score": round(tie_brier, 6) if tie_brier is not None else None,
            "mean_predicted_probability": (
                round(sum(p for p, _ in tie_samples) / len(tie_samples), 6)
                if tie_samples else None
            ),
            "observed_tie_rate": (
                round(sum(y for _, y in tie_samples) / len(tie_samples), 6)
                if tie_samples else None
            ),
        },
        "exclusions": exclusions,
        "notes": [
            "Solo se evalúan snapshots liquidados del modelo oficial 2.0.0-matchup.",
            "Se excluyen snapshots sin fecha de corte anterior al inicio del partido.",
            "Este informe evalúa pronósticos guardados; no reconstruye temporadas históricas con estadísticas actuales.",
            "El empate tras nueve entradas solo se evalúa si el feed ofrece datos válidos por entrada.",
            "Estas métricas descriptivas no modifican las probabilidades oficiales ni las predicciones guardadas.",
        ],
    }


def actual_tie_after_nine(feed):
    """Return True/False from a completed game's first nine inning scores, else None."""
    if not isinstance(feed, dict):
        return None
    game_status = (feed.get("gameData") or {}).get("status") or {}
    if str(game_status.get("abstractGameState") or "").lower() != "final":
        return None
    linescore = ((feed.get("liveData") or {}).get("linescore") or {})
    scheduled = _finite_number(linescore.get("scheduledInnings"))
    if scheduled is not None and scheduled < 9:
        return None
    innings = linescore.get("innings")
    if not isinstance(innings, list) or len(innings) < 9:
        return None
    home_total = 0
    away_total = 0
    for inning in innings[:9]:
        if not isinstance(inning, dict):
            return None
        home = _finite_number((inning.get("home") or {}).get("runs"))
        away = _finite_number((inning.get("away") or {}).get("runs"))
        if home is None or away is None or home < 0 or away < 0:
            return None
        home_total += home
        away_total += away
    return home_total == away_total
