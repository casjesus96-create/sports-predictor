"""Chronological read-only walk-forward backtest for NFL advanced features."""
import csv
import gzip
import io
import math
from datetime import datetime, timezone

import requests

from nfl_client import load_schedule
from nfl_data_coverage import NFLVERSE_RELEASES
from nfl_prediction import MODEL_VERSION, calculate_probability

TIMEOUT_SECONDS = 25
FEATURES = (
    "passing_epa",
    "rushing_epa",
    "turnovers",
    "offensive_epa_per_play",
    "success_rate",
    "third_down_rate",
    "defensive_epa_allowed",
    "point_diff",
)


def _time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _num(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _download_rows(session, url):
    response = session.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as zipped:
        reader = csv.DictReader(io.TextIOWrapper(zipped, encoding="utf-8-sig", errors="replace"))
        return list(reader)


def _source_rows(session, season):
    base = NFLVERSE_RELEASES
    team = _download_rows(session, f"{base}/stats_team/stats_team_week_{season}.csv.gz")
    pbp = _download_rows(session, f"{base}/pbp/play_by_play_{season}.csv.gz")
    return team, pbp


def _metric_map(team_rows, pbp_rows, completed):
    metrics = {}
    for row in team_rows:
        gid = str(row.get("game_id") or "")
        game = completed.get(gid)
        team = str(row.get("team") or "").upper()
        if not game or not team:
            continue
        passing = _num(row.get("passing_epa"))
        rushing = _num(row.get("rushing_epa"))
        ints = _num(row.get("passing_interceptions"))
        fumbles = _num(row.get("rushing_fumbles_lost"))
        item = metrics.setdefault((team, gid), {})
        if passing is not None:
            item["passing_epa"] = passing
        if rushing is not None:
            item["rushing_epa"] = rushing
        if ints is not None or fumbles is not None:
            item["turnovers"] = (ints or 0.0) + (fumbles or 0.0)

    pbp = {}
    for row in pbp_rows:
        gid = str(row.get("game_id") or "")
        if gid not in completed:
            continue
        if str(row.get("play_deleted") or "").lower() in {"1", "true", "yes"}:
            continue
        if str(row.get("aborted_play") or "").lower() in {"1", "true", "yes"}:
            continue
        offense = str(row.get("posteam") or "").upper()
        defense = str(row.get("defteam") or "").upper()
        epa = _num(row.get("epa"))
        success = _num(row.get("success"))
        down = _num(row.get("down"))
        converted = str(row.get("third_down_converted") or "").lower() in {"1", "true", "yes"}
        if offense:
            bucket = pbp.setdefault((offense, gid), {"epa_sum": 0.0, "epa_n": 0, "success_n": 0, "success_yes": 0, "third_n": 0, "third_yes": 0})
            if epa is not None:
                bucket["epa_sum"] += epa
                bucket["epa_n"] += 1
            if success is not None:
                bucket["success_n"] += 1
                bucket["success_yes"] += int(success > 0)
            if down == 3:
                bucket["third_n"] += 1
                bucket["third_yes"] += int(converted)
        if defense and epa is not None:
            bucket = pbp.setdefault(("DEF:" + defense, gid), {"epa_sum": 0.0, "epa_n": 0})
            bucket["epa_sum"] += epa
            bucket["epa_n"] += 1

    for (team, gid), bucket in pbp.items():
        if team.startswith("DEF:"):
            if bucket["epa_n"]:
                metrics.setdefault((team[4:], gid), {})["defensive_epa_allowed"] = bucket["epa_sum"] / bucket["epa_n"]
            continue
        item = metrics.setdefault((team, gid), {})
        if bucket.get("epa_n"):
            item["offensive_epa_per_play"] = bucket["epa_sum"] / bucket["epa_n"]
        if bucket.get("success_n"):
            item["success_rate"] = bucket["success_yes"] / bucket["success_n"]
        if bucket.get("third_n"):
            item["third_down_rate"] = bucket["third_yes"] / bucket["third_n"]
    return metrics


def _team_features(team, cutoff, games, metrics):
    history = []
    for game in games:
        kickoff = _time(game.get("kickoff"))
        if kickoff is None or kickoff >= cutoff or game.get("home_score") is None or game.get("away_score") is None:
            continue
        if team not in (game.get("home"), game.get("away")):
            continue
        item = dict(metrics.get((team, str(game.get("game_id"))), {}))
        if game.get("home") == team:
            item["point_diff"] = float(game["home_score"]) - float(game["away_score"])
        else:
            item["point_diff"] = float(game["away_score"]) - float(game["home_score"])
        item["_kickoff"] = kickoff
        history.append(item)
    history.sort(key=lambda x: x["_kickoff"], reverse=True)
    history = history[:5]
    values = []
    for feature in FEATURES:
        present = [x[feature] for x in history if x.get(feature) is not None]
        values.append(sum(present) / len(present) if present else 0.0)
    return values, len(history)


def _baseline(game, season_games):
    kickoff = _time(game["kickoff"])
    team_values = {}
    for team in (game["home"], game["away"]):
        prior = []
        for item in season_games:
            dt = _time(item.get("kickoff"))
            if (item.get("game_type") == "REG" and dt is not None and dt < kickoff
                    and item.get("home_score") is not None and item.get("away_score") is not None
                    and team in (item.get("home"), item.get("away"))):
                prior.append(item)
        prior.sort(key=lambda x: _time(x["kickoff"]), reverse=True)
        diffs, pf, pa, wins = [], [], [], 0
        for item in prior:
            home = item["home"] == team
            scored = float(item["home_score"] if home else item["away_score"])
            conceded = float(item["away_score"] if home else item["home_score"])
            diffs.append(scored - conceded)
            pf.append(scored)
            pa.append(conceded)
            wins += int(scored > conceded)
        recent = diffs[:5]
        n = len(prior)
        team_values[team] = {
            "games": n, "point_diff_per_game": sum(diffs) / n if n else 0.0,
            "points_for_per_game": sum(pf) / n if n else 21.0,
            "points_against_per_game": sum(pa) / n if n else 21.0,
            "recent_point_diff_per_game": sum(recent) / len(recent) if recent else 0.0,
            "recent_win_rate": sum(x > 0 for x in recent) / len(recent) if recent else 0.5,
            "latest_kickoff": _time(prior[0]["kickoff"]) if prior else None,
        }
    def rest(team):
        previous = team_values[team]["latest_kickoff"]
        return max(0.0, (kickoff - previous).total_seconds() / 86400.0) if previous else 7.0
    p = calculate_probability(team_values[game["home"]], team_values[game["away"]], rest(game["home"]), rest(game["away"]))
    return float(p["home"])


def _fit_logistic(rows, dimensions):
    if len(rows) < 2:
        return None
    xs = [row[0] for row in rows]
    ys = [row[1] for row in rows]
    means = [sum(x[j] for x in xs) / len(xs) for j in range(dimensions)]
    scales = []
    for j in range(dimensions):
        variance = sum((x[j] - means[j]) ** 2 for x in xs) / len(xs)
        scales.append(math.sqrt(variance) or 1.0)
    normalized = [[(x[j] - means[j]) / scales[j] for j in range(dimensions)] for x in xs]
    weights = [0.0] * (dimensions + 1)
    # Deterministic batch gradient descent; training data strictly precedes target kickoff.
    for _ in range(350):
        gradients = [0.0] * len(weights)
        for x, y in zip(normalized, ys):
            z = max(-20.0, min(20.0, weights[0] + sum(weights[j + 1] * x[j] for j in range(dimensions))))
            p = 1.0 / (1.0 + math.exp(-z))
            error = p - y
            gradients[0] += error
            for j in range(dimensions):
                gradients[j + 1] += error * x[j]
        rate = 0.08 / len(rows)
        weights = [weights[j] - rate * (gradients[j] + (0.01 * weights[j] if j else 0.0)) for j in range(len(weights))]
    return means, scales, weights


def _predict_logistic(model, features):
    means, scales, weights = model
    z = weights[0] + sum(weights[j + 1] * ((features[j] - means[j]) / scales[j]) for j in range(len(features)))
    z = max(-20.0, min(20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _score(probabilities, outcomes):
    if not outcomes:
        return {"sample_size": 0, "accuracy_pct": None, "brier_score": None, "log_loss": None, "calibration": []}
    brier = []
    logloss = []
    correct = 0
    bins = {label: [] for label in ("50-60%", "60-70%", "70-80%", "80-90%", "90-100%")}
    for p, y in zip(probabilities, outcomes):
        p = max(0.001, min(0.999, p))
        brier.append((p - y) ** 2)
        logloss.append(-(y * math.log(p) + (1 - y) * math.log(1 - p)))
        correct += int((p >= 0.5) == bool(y))
        label = next((name for name, lo, hi in (("50-60%", .5, .6), ("60-70%", .6, .7), ("70-80%", .7, .8), ("80-90%", .8, .9), ("90-100%", .9, 1.001)) if lo <= max(p, 1-p) < hi), None)
        if label:
            bins[label].append((max(p, 1-p), int((p >= .5) == bool(y))))
    calibration = [{"confidence_bin": k, "count": len(v), "mean_confidence": round(sum(a for a, _ in v)/len(v), 4), "observed_accuracy": round(sum(b for _, b in v)/len(v), 4)} for k, v in bins.items() if v]
    return {"sample_size": len(outcomes), "accuracy_pct": round(100 * correct / len(outcomes), 2), "brier_score": round(sum(brier)/len(brier), 6), "log_loss": round(sum(logloss)/len(logloss), 6), "calibration": calibration}


def run_nfl_walk_forward_backtest(start_season=2023, end_season=2026, min_training_games=100, session=requests):
    """Compare the frozen official model with a fitted experimental model without persistence."""
    if start_season < 1999 or end_season > 2100 or start_season > end_season:
        raise ValueError("Rango de temporadas no válido.")
    schedules = {}
    all_games = []
    metrics = {}
    source_status = []
    for season in range(start_season, end_season + 1):
        games = load_schedule(season=season)
        schedules[season] = games
        completed = {str(g["game_id"]): g for g in games if g.get("game_id") and g.get("game_type") == "REG" and g.get("home_score") is not None and g.get("away_score") is not None and _time(g.get("kickoff"))}
        try:
            team_rows, pbp_rows = _source_rows(session, season)
            season_metrics = _metric_map(team_rows, pbp_rows, completed)
            metrics.update(season_metrics)
            source_status.append({"season": season, "available": True, "team_rows": len(team_rows), "pbp_rows": len(pbp_rows), "error": None})
        except (requests.RequestException, OSError, EOFError, csv.Error, ValueError) as exc:
            source_status.append({"season": season, "available": False, "team_rows": 0, "pbp_rows": 0, "error": type(exc).__name__})
        for game in games:
            if game.get("game_type") == "REG" and game.get("home") and game.get("away") and _time(game.get("kickoff")):
                all_games.append(game)
    all_games.sort(key=lambda g: _time(g["kickoff"]))
    training = []
    baseline_probs, candidate_probs, outcomes = [], [], []
    skipped = {"no_result": 0, "insufficient_training": 0, "tie": 0, "unavailable_features": 0}
    evaluated = []
    for target in all_games:
        cutoff = _time(target["kickoff"])
        home_score, away_score = _num(target.get("home_score")), _num(target.get("away_score"))
        home_vec, home_n = _team_features(target["home"], cutoff, [g for g in all_games if _time(g["kickoff"]) < cutoff and g.get("season") == target.get("season")], metrics)
        away_vec, away_n = _team_features(target["away"], cutoff, [g for g in all_games if _time(g["kickoff"]) < cutoff and g.get("season") == target.get("season")], metrics)
        features = [a - b for a, b in zip(home_vec, away_vec)]
        model = _fit_logistic(training, len(FEATURES)) if len(training) >= min_training_games else None
        if home_score is None or away_score is None:
            skipped["no_result"] += 1
            continue
        if home_score == away_score:
            skipped["tie"] += 1
            continue
        if not source_status or not any(s["available"] and s["season"] == int(target.get("season", -1)) for s in source_status):
            skipped["unavailable_features"] += 1
            continue
        if model is None:
            skipped["insufficient_training"] += 1
        else:
            y = 1 if home_score > away_score else 0
            p_base = _baseline(target, schedules[int(target["season"])])
            p_candidate = _predict_logistic(model, features)
            baseline_probs.append(p_base)
            candidate_probs.append(p_candidate)
            outcomes.append(y)
            evaluated.append({"game_id": str(target["game_id"]), "season": int(target["season"]), "home_probability_official": round(p_base, 6), "home_probability_experimental": round(p_candidate, 6), "actual_home_win": bool(y), "prior_training_games": len(training), "home_history_games": home_n, "away_history_games": away_n})
        # Add this game's labeled feature vector only after scoring/skipping it.
        if home_score is not None and away_score is not None and home_score != away_score:
            training.append((features, 1 if home_score > away_score else 0))
    base_score = _score(baseline_probs, outcomes)
    candidate_score = _score(candidate_probs, outcomes)
    return {
        "success": True, "sport": "NFL", "season_range": {"start": start_season, "end": end_season},
        "model_version": MODEL_VERSION, "candidate_version": "NFL-ADVANCED-WF-EXPERIMENTAL-1",
        "read_only": True, "model_impact": "none", "predictions_persisted": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {"walk_forward": True, "target_cutoff": "strictly before target kickoff", "training_cutoff": "only earlier kickoff games; target is added to training after evaluation", "same_sample_comparison": True, "candidate_features": list(FEATURES), "training": "deterministic logistic regression refit at each target using only earlier labeled games", "limitations": "experimental candidate; source publication timing within a week and feature availability require further verification before any production use"},
        "sources": source_status, "scored_games": len(outcomes), "skipped": skipped,
        "official": base_score, "experimental": candidate_score,
        "comparison": {"brier_improvement": round(base_score["brier_score"] - candidate_score["brier_score"], 6) if outcomes else None, "log_loss_improvement": round(base_score["log_loss"] - candidate_score["log_loss"], 6) if outcomes else None, "accuracy_delta_percentage_points": round(candidate_score["accuracy_pct"] - base_score["accuracy_pct"], 2) if outcomes else None},
        "sample_predictions": evaluated[-20:],
        "activation": "not_eligible_automatically",
    }
