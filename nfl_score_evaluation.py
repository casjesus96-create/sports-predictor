"""Chronological NFL score-line evaluation; read-only and experimental."""
from __future__ import annotations

import math
from collections import defaultdict

from nfl_client import load_schedule
from nfl_walk_forward_backtest import _baseline, _time


def _stats_before(team, cutoff, games):
    prior = []
    for game in games:
        kickoff = _time(game.get("kickoff"))
        if (
            kickoff is None or kickoff >= cutoff
            or game.get("game_type") != "REG"
            or game.get("home_score") is None
            or game.get("away_score") is None
            or team not in (game.get("home"), game.get("away"))
        ):
            continue
        is_home = game.get("home") == team
        scored = float(game["home_score"] if is_home else game["away_score"])
        allowed = float(game["away_score"] if is_home else game["home_score"])
        prior.append((kickoff, scored, allowed))
    prior.sort(key=lambda item: item[0])
    if not prior:
        return None
    recent = prior[-5:]
    avg = lambda values: sum(values) / len(values)
    return {
        "games": len(prior),
        "points_for": avg([x[1] for x in prior]),
        "points_against": avg([x[2] for x in prior]),
        "recent_points_for": avg([x[1] for x in recent]),
        "recent_points_against": avg([x[2] for x in recent]),
    }


def _projections(game, history):
    kickoff = _time(game.get("kickoff"))
    home = _stats_before(game["home"], kickoff, history)
    away = _stats_before(game["away"], kickoff, history)
    if not home or not away:
        return None
    base_home = 0.55 * home["points_for"] + 0.45 * away["points_against"] + 1.5
    base_away = 0.55 * away["points_for"] + 0.45 * home["points_against"]
    enriched_home = (
        0.35 * home["points_for"] + 0.25 * home["recent_points_for"]
        + 0.25 * away["points_against"] + 0.15 * away["recent_points_against"] + 1.5
    )
    enriched_away = (
        0.35 * away["points_for"] + 0.25 * away["recent_points_for"]
        + 0.25 * home["points_against"] + 0.15 * home["recent_points_against"]
    )
    clamp = lambda x: max(0.0, min(50.0, x))
    return {
        "baseline": (clamp(base_home), clamp(base_away)),
        "enriched": (clamp(enriched_home), clamp(enriched_away)),
        "sample": {"home_games": home["games"], "away_games": away["games"]},
    }


def _summary(rows):
    if not rows:
        return {"sample_size": 0, "margin_mae": None, "total_mae": None}
    return {
        "sample_size": len(rows),
        "margin_mae": round(sum(abs(r["pred_margin"] - r["actual_margin"]) for r in rows) / len(rows), 4),
        "total_mae": round(sum(abs(r["pred_total"] - r["actual_total"]) for r in rows) / len(rows), 4),
    }


def run_nfl_score_walk_forward(start_season=2023, end_season=2026):
    """Score every final game in chronological order using only earlier scores."""
    if start_season < 1999 or end_season > 2100 or start_season > end_season:
        raise ValueError("Rango de temporadas no válido.")
    all_games = []
    for season in range(start_season, end_season + 1):
        all_games.extend(load_schedule(season=season))
    all_games.sort(key=lambda g: _time(g.get("kickoff")) or _time("1970-01-01T00:00:00Z"))

    baseline_rows, enriched_rows = [], []
    by_season = defaultdict(lambda: {"baseline": [], "enriched": []})
    by_confidence = defaultdict(lambda: {"baseline": [], "enriched": []})
    market_total_rows = []
    skipped = {"no_final_score": 0, "no_prior_history": 0, "no_market_total": 0}
    evaluated = []

    for target in all_games:
        if target.get("game_type") != "REG" or not target.get("home") or not target.get("away"):
            continue
        hs, aws = target.get("home_score"), target.get("away_score")
        if hs is None or aws is None:
            skipped["no_final_score"] += 1
            continue
        cutoff = _time(target.get("kickoff"))
        if cutoff is None:
            continue
        # Strict chronological cutoff. All records at/after kickoff are excluded.
        prior = [g for g in all_games if _time(g.get("kickoff")) and _time(g["kickoff"]) < cutoff]
        projections = _projections(target, prior)
        if not projections:
            skipped["no_prior_history"] += 1
            continue
        actual_margin = float(hs) - float(aws)
        actual_total = float(hs) + float(aws)
        season = str(target.get("season"))
        try:
            confidence = max(_baseline(target, prior), 1 - _baseline(target, prior))
        except Exception:
            confidence = 0.5
        confidence_bin = "50-60%" if confidence < .60 else "60-70%" if confidence < .70 else "70-80%" if confidence < .80 else "80-90%" if confidence < .90 else "90-95%"
        for version in ("baseline", "enriched"):
            home_points, away_points = projections[version]
            row = {
                "pred_margin": home_points - away_points,
                "pred_total": home_points + away_points,
                "actual_margin": actual_margin,
                "actual_total": actual_total,
            }
            (baseline_rows if version == "baseline" else enriched_rows).append(row)
            by_season[season][version].append(row)
            by_confidence[confidence_bin][version].append(row)
        market_total = target.get("total_line")
        market_result = None
        model_total_result = None
        if market_total is not None and math.isfinite(float(market_total)):
            market_total = float(market_total)
            market_result = "over" if actual_total > market_total else "under" if actual_total < market_total else "push"
            predicted_total = sum(projections["enriched"])
            model_total_result = "over" if predicted_total > market_total else "under" if predicted_total < market_total else "push"
            if market_result != "push":
                market_total_rows.append({
                    "season": season, "confidence_bin": confidence_bin,
                    "market_correct": market_result == ("over" if actual_total > market_total else "under"),
                    "projection_direction_correct": model_total_result == market_result,
                    "market_line": market_total, "actual_total": actual_total,
                    "projected_total_enriched": round(predicted_total, 2),
                })
        else:
            skipped["no_market_total"] += 1
        evaluated.append({
            "game_id": str(target.get("game_id")), "season": int(target.get("season")),
            "kickoff": cutoff.isoformat(), "actual_home_score": hs, "actual_away_score": aws,
            "baseline_projected_home": round(projections["baseline"][0], 2),
            "baseline_projected_away": round(projections["baseline"][1], 2),
            "enriched_projected_home": round(projections["enriched"][0], 2),
            "enriched_projected_away": round(projections["enriched"][1], 2),
            "market_total": market_total,
            "confidence_bin": confidence_bin,
        })

    market_n = len(market_total_rows)
    market_summary = {
        "sample_size": market_n,
        "market_total_direction_accuracy_pct": round(100 * sum(r["projection_direction_correct"] for r in market_total_rows) / market_n, 2) if market_n else None,
        "by_season": {},
        "by_confidence": {},
        "note": "Se evalúa la dirección over/under del total; no es ROI ni rentabilidad, porque no se incluyen cuotas/precios de apuesta.",
    }
    for key_name, key in (("by_season", "season"), ("by_confidence", "confidence_bin")):
        grouped = defaultdict(list)
        for row in market_total_rows:
            grouped[row[key]].append(row)
        market_summary[key_name] = {
            group: {
                "sample_size": len(items),
                "projection_direction_accuracy_pct": round(100 * sum(r["projection_direction_correct"] for r in items) / len(items), 2),
            } for group, items in sorted(grouped.items())
        }

    return {
        "success": True, "sport": "NFL",
        "season_range": {"start": start_season, "end": end_season},
        "read_only": True, "predictions_persisted": False, "model_impact": "none",
        "candidate_version": "NFL-SCORE-RECENCY-EXPERIMENTAL-1",
        "method": {
            "walk_forward": True, "cutoff": "solo partidos finalizados con kickoff estrictamente anterior al partido objetivo",
            "baseline_formula": "0.55 × puntos propios por partido + 0.45 × puntos permitidos del rival + 1.5 localía",
            "enriched_formula": "35% puntos propios de temporada + 25% puntos propios últimos 5 + 25% puntos permitidos de temporada del rival + 15% puntos permitidos últimos 5 del rival + 1.5 localía",
            "limitations": "El calendario histórico puede incluir líneas de mercado retrospectivas; no se afirma que esas líneas estuvieran disponibles en el mismo instante pregame. Solo mide dirección del total, no ROI.",
        },
        "scored_games": len(enriched_rows), "skipped": skipped,
        "baseline": _summary(baseline_rows), "enriched": _summary(enriched_rows),
        "comparison": {
            "margin_mae_improvement": round(_summary(baseline_rows)["margin_mae"] - _summary(enriched_rows)["margin_mae"], 4) if enriched_rows else None,
            "total_mae_improvement": round(_summary(baseline_rows)["total_mae"] - _summary(enriched_rows)["total_mae"], 4) if enriched_rows else None,
        },
        "by_season": {
            season: {"baseline": _summary(values["baseline"]), "enriched": _summary(values["enriched"])}
            for season, values in sorted(by_season.items())
        },
        "by_confidence": {
            bucket: {"baseline": _summary(values["baseline"]), "enriched": _summary(values["enriched"])}
            for bucket, values in sorted(by_confidence.items())
        },
        "market_total": market_summary,
        "sample_predictions": evaluated[-25:],
        "activation": "not_eligible_automatically",
    }
