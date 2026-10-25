"""Read-only chronological walk-forward evaluation of football 1X2 models.

The evaluator never writes snapshots or changes the official model. For each
finished fixture it trains only on FINISHED fixtures with kickoff strictly
earlier than the target kickoff, then scores base and H2H candidate on the same
eligible target sample. Input must contain matches from one competition.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from football_h2h_experiment import evaluate_h2h_candidate
from football_model import MODEL_VERSION, predict_1x2

OUTCOMES = ("home", "draw", "away")
EPSILON = 1e-15
CALIBRATION_BINS = 5


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _score(match: dict[str, Any]) -> tuple[int, int] | None:
    if str(match.get("status", "")).upper() != "FINISHED":
        return None
    full_time = ((match.get("score") or {}).get("fullTime") or {})
    home, away = full_time.get("home"), full_time.get("away")
    if (not isinstance(home, int) or isinstance(home, bool) or home < 0
            or not isinstance(away, int) or isinstance(away, bool) or away < 0):
        return None
    return home, away


def _probabilities(prediction: dict[str, Any], key: str) -> dict[str, float] | None:
    raw = prediction.get(key) or {}
    try:
        values = {outcome: float(raw[outcome]) for outcome in OUTCOMES}
    except (KeyError, TypeError, ValueError):
        return None
    if any(not math.isfinite(p) or p < 0 or p > 1 for p in values.values()):
        return None
    total = sum(values.values())
    if total <= 0:
        return None
    return {outcome: values[outcome] / total for outcome in OUTCOMES}


def _metrics(rows: list[dict[str, Any]], probability_key: str) -> dict[str, Any]:
    if not rows:
        return {
            "sample_size": 0, "accuracy": None, "brier_score": None,
            "log_loss": None, "outcome_calibration": {},
        }
    correct = 0
    brier_total = 0.0
    log_loss_total = 0.0
    per_outcome = {
        outcome: {"mean_predicted_probability": 0.0, "observed_rate": 0.0, "brier_component": 0.0}
        for outcome in OUTCOMES
    }
    calibration = {
        outcome: [
            {"range": f"[{i / CALIBRATION_BINS:.1f},{(i + 1) / CALIBRATION_BINS:.1f}{']' if i == CALIBRATION_BINS - 1 else ')'}",
             "n": 0, "mean_predicted_probability": 0.0, "observed_rate": 0.0}
            for i in range(CALIBRATION_BINS)
        ]
        for outcome in OUTCOMES
    }

    for row in rows:
        probs = row[probability_key]
        actual = row["actual_outcome"]
        predicted = max(OUTCOMES, key=lambda name: probs[name])
        correct += predicted == actual
        log_loss_total -= math.log(max(EPSILON, min(1.0, probs[actual])))
        squared_sum = 0.0
        for outcome in OUTCOMES:
            observed = 1.0 if actual == outcome else 0.0
            p = probs[outcome]
            squared = (p - observed) ** 2
            squared_sum += squared
            per_outcome[outcome]["mean_predicted_probability"] += p
            per_outcome[outcome]["observed_rate"] += observed
            per_outcome[outcome]["brier_component"] += squared
            bucket_index = min(CALIBRATION_BINS - 1, int(p * CALIBRATION_BINS))
            bucket = calibration[outcome][bucket_index]
            bucket["n"] += 1
            bucket["mean_predicted_probability"] += p
            bucket["observed_rate"] += observed
        brier_total += squared_sum

    n = len(rows)
    for outcome in OUTCOMES:
        per_outcome[outcome] = {
            key: round(value / n, 6)
            for key, value in per_outcome[outcome].items()
        }
        for bucket in calibration[outcome]:
            if bucket["n"]:
                bucket["mean_predicted_probability"] = round(bucket["mean_predicted_probability"] / bucket["n"], 6)
                bucket["observed_rate"] = round(bucket["observed_rate"] / bucket["n"], 6)
            else:
                bucket["mean_predicted_probability"] = None
                bucket["observed_rate"] = None
    return {
        "sample_size": n,
        "accuracy": round(correct / n, 6),
        # Multiclass Brier: sum of squared errors over home/draw/away, averaged per match.
        "brier_score": round(brier_total / n, 6),
        "log_loss": round(log_loss_total / n, 6),
        "outcome_calibration": per_outcome,
        "reliability_bins": calibration,
    }


def run_chronological_backtest(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate both 1X2 variants without look-ahead leakage or database writes.

    Only fixtures with valid timezone-aware kickoff, FINISHED status, and numeric
    full-time scores are scored. Training history is restricted to fixtures with
    kickoff strictly earlier than the target, so simultaneous kickoffs are
    excluded from one another's training data.
    """
    normalized: list[tuple[datetime, dict[str, Any], tuple[int, int]]] = []
    excluded_targets = 0
    for match in matches:
        kickoff = _date(match.get("utcDate") or match.get("date"))
        score = _score(match)
        home = (match.get("homeTeam") or {}).get("name")
        away = (match.get("awayTeam") or {}).get("name")
        if kickoff is None or score is None or not home or not away or str(home).casefold() == str(away).casefold():
            excluded_targets += 1
            continue
        normalized.append((kickoff, match, score))
    normalized.sort(key=lambda item: (item[0], str(item[1].get("id", ""))))

    scored_rows: list[dict[str, Any]] = []
    skipped_unavailable = 0
    for kickoff, target, score in normalized:
        history = [
            prior for prior in matches
            if (_date(prior.get("utcDate") or prior.get("date")) is not None
                and _date(prior.get("utcDate") or prior.get("date")) < kickoff
                and _score(prior) is not None)
        ]
        home_name = str((target.get("homeTeam") or {}).get("name"))
        away_name = str((target.get("awayTeam") or {}).get("name"))
        base = predict_1x2(home_name, away_name, history)
        if not base.get("available"):
            skipped_unavailable += 1
            continue
        candidate = evaluate_h2h_candidate(
            home_name, away_name, kickoff.isoformat(), base, history
        )
        base_probs = _probabilities(base, "probabilities")
        candidate_probs = _probabilities(candidate, "candidate_probabilities")
        if not base_probs or not candidate.get("available") or not candidate_probs:
            skipped_unavailable += 1
            continue
        home_score, away_score = score
        actual = "home" if home_score > away_score else "away" if home_score < away_score else "draw"
        scored_rows.append({
            "match_id": target.get("id"),
            "kickoff_at": kickoff.isoformat(),
            "home_team": home_name,
            "away_team": away_name,
            "actual_outcome": actual,
            "base": base_probs,
            "candidate": candidate_probs,
            "h2h_valid_meetings": (candidate.get("h2h") or {}).get("valid_meetings", 0),
        })

    base_metrics = _metrics(scored_rows, "base")
    candidate_metrics = _metrics(scored_rows, "candidate")
    return {
        "status": "COMPLETED" if scored_rows else "INSUFFICIENT_DATA",
        "evaluation_type": "chronological_walk_forward",
        "official_model_version": MODEL_VERSION,
        "candidate_model_version": "FOOTBALL-H2H-SHADOW-0.1.0",
        "read_only": True,
        "training_rule": "Solo partidos FINISHED con kickoff estrictamente anterior al partido evaluado; misma hora de inicio queda excluida.",
        "scoring_rule": "Ambas variantes se comparan sobre exactamente la misma muestra elegible.",
        "input_matches": len(matches),
        "eligible_finished_matches": len(normalized),
        "scored_matches": len(scored_rows),
        "excluded_invalid_or_unfinished_targets": excluded_targets,
        "skipped_base_unavailable_or_invalid": skipped_unavailable,
        "metrics": {
            "base": base_metrics,
            "h2h_candidate": candidate_metrics,
            "delta_candidate_minus_base": {
                "accuracy": round(candidate_metrics["accuracy"] - base_metrics["accuracy"], 6)
                if scored_rows else None,
                "brier_score": round(candidate_metrics["brier_score"] - base_metrics["brier_score"], 6)
                if scored_rows else None,
                "log_loss": round(candidate_metrics["log_loss"] - base_metrics["log_loss"], 6)
                if scored_rows else None,
                "interpretation": "Para Brier Score y Log Loss, un delta negativo favorece al candidato; para accuracy, uno positivo favorece al candidato.",
            },
        },
        "per_match": scored_rows,
        "limitations": [
            "Backtest sobre el conjunto de partidos suministrado; no descarga datos ni escribe en Supabase.",
            "La variante H2H usa solo enfrentamientos presentes en el mismo conjunto de entrada y anteriores al kickoff.",
            "Si el proveedor no entrega temporadas históricas completas, los resultados no representan toda la historia de la competición.",
            "No constituye evidencia de rentabilidad ni autoriza activar el candidato como modelo oficial.",
        ],
    }
