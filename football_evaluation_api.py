"""Read-only evaluation of settled football 1X2 prediction snapshots."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from repository import get_supabase_client
from football_model import MODEL_VERSION

router = APIRouter(prefix="/api/v1/football", tags=["Football evaluation"])


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


BOOTSTRAP_REPLICATES = 1000
MIN_CROSS_LEAGUE_MATCHES = 50
MIN_CROSS_LEAGUE_DATES = 10
CROSS_LEAGUE_CODES = ("BL1", "FL1", "PD", "PL", "SA")


def _competition_calibration(items: list[tuple], seed: int = 0) -> dict:
    """One-vs-rest calibration bias with date-cluster uncertainty."""
    n = len(items)
    dates = sorted({
        str(item[0].get("kickoff_at") or "")[:10]
        for item in items if str(item[0].get("kickoff_at") or "")[:10]
    })
    grouped: dict[str, list[tuple]] = defaultdict(list)
    for item in items:
        day = str(item[0].get("kickoff_at") or "")[:10]
        if day:
            grouped[day].append(item)

    outcomes = {}
    for outcome_index, outcome in enumerate(("home", "draw", "away")):
        predicted = [item[1][outcome_index] for item in items]
        observed = [1.0 if item[2] == outcome else 0.0 for item in items]
        bias = (sum(predicted) - sum(observed)) / n if n else None
        samples = []
        clusters = list(grouped.values())
        if len(clusters) >= 2:
            rng = random.Random(seed + outcome_index)
            for _ in range(BOOTSTRAP_REPLICATES):
                sampled = [clusters[rng.randrange(len(clusters))] for _ in range(len(clusters))]
                sampled_n = sum(len(cluster) for cluster in sampled)
                predicted_sum = sum(item[1][outcome_index] for cluster in sampled for item in cluster)
                observed_sum = sum(
                    1.0 if item[2] == outcome else 0.0
                    for cluster in sampled for item in cluster
                )
                samples.append((predicted_sum - observed_sum) / sampled_n)
        samples.sort()
        ci = None
        if len(samples) >= 500:
            ci = [
                round(samples[int(0.025 * (len(samples) - 1))], 6),
                round(samples[int(0.975 * (len(samples) - 1))], 6),
            ]
        outcomes[outcome] = {
            "mean_predicted_probability": round(sum(predicted) / n, 6) if n else None,
            "observed_frequency": round(sum(observed) / n, 6) if n else None,
            "bias": round(bias, 6) if bias is not None else None,
            "bias_ci_95": ci,
            "interpretation": (
                "SOBREESTIMACION" if ci and ci[0] > 0 else
                "SUBESTIMACION" if ci and ci[1] < 0 else
                "SIN_EVIDENCIA_CONCLUYENTE" if ci else "IC95_NO_ESTIMABLE"
            ),
        }
    eligible = n >= MIN_CROSS_LEAGUE_MATCHES and len(dates) >= MIN_CROSS_LEAGUE_DATES
    return {
        "sample_size": n,
        "independent_dates": len(dates),
        "date_start": dates[0] if dates else None,
        "date_end": dates[-1] if dates else None,
        "eligible_for_descriptive_comparison": eligible,
        "minimum_matches": MIN_CROSS_LEAGUE_MATCHES,
        "minimum_independent_dates": MIN_CROSS_LEAGUE_DATES,
        "outcomes": outcomes,
        "scope": "official_model_settled_snapshots_only",
        "uncertainty_method": "Bootstrap percentil por fecha completa; 1000 réplicas deterministas.",
    }



def evaluate_rows(rows: list[dict]) -> dict:
    """Compute multiclass Brier, log loss, accuracy and outcome breakdown."""
    valid = []
    skipped = 0
    for row in rows:
        probs = [_number(row.get(k)) for k in (
            "home_probability", "draw_probability", "away_probability"
        )]
        hs, aws = _number(row.get("actual_home_score")), _number(row.get("actual_away_score"))
        if (any(p is None or p < 0 or p > 1 for p in probs)
                or abs(sum(probs) - 1.0) > 0.02
                or hs is None or aws is None or hs < 0 or aws < 0):
            skipped += 1
            continue
        total = sum(probs)
        probs = [p / total for p in probs]
        outcome = "home" if hs > aws else "away" if hs < aws else "draw"
        actual = {"home": 0, "draw": 1, "away": 2}[outcome]
        valid.append((row, probs, outcome, actual))

    if not valid:
        return {"sample_size": 0, "skipped_rows": skipped, "metrics": None,
                "by_outcome": {}, "by_competition": {}, "calibration": [],
                "status": "insufficient_data"}

    eps = 1e-15
    brier = sum(sum((p - (i == actual)) ** 2 for i, p in enumerate(probs))
                for _, probs, _, actual in valid) / len(valid)
    log_loss = -sum(math.log(max(eps, probs[actual])) for _, probs, _, actual in valid) / len(valid)
    correct = sum(max(range(3), key=lambda i: probs[i]) == actual
                  for _, probs, _, actual in valid)

    def group_summary(items):
        n = len(items)
        return {
            "sample_size": n,
            "accuracy": round(sum(max(range(3), key=lambda i: p[i]) == a for _, p, _, a in items) / n, 6),
            "brier_score": round(sum(sum((p[i] - (i == a)) ** 2 for i in range(3)) for _, p, _, a in items) / n, 6),
            "log_loss": round(-sum(math.log(max(eps, p[a])) for _, p, _, a in items) / n, 6),
        }

    outcomes = {}
    for outcome in ("home", "draw", "away"):
        items = [item for item in valid if item[2] == outcome]
        outcomes[outcome] = {
            "actual_count": len(items),
            "mean_predicted_probability": round(sum(item[1][{"home":0,"draw":1,"away":2}[outcome]] for item in valid) / len(valid), 6),
            "observed_frequency": round(len(items) / len(valid), 6),
        }

    competitions = defaultdict(list)
    for item in valid:
        competitions[str(item[0].get("competition_code") or "UNKNOWN")].append(item)

    calibration = []
    for index, label in enumerate(("home", "draw", "away")):
        calibration.append({
            "outcome": label,
            "mean_predicted_probability": outcomes[label]["mean_predicted_probability"],
            "observed_frequency": outcomes[label]["observed_frequency"],
            "absolute_gap": round(abs(outcomes[label]["mean_predicted_probability"] - outcomes[label]["observed_frequency"]), 6),
        })

    return {
        "sample_size": len(valid),
        "skipped_rows": skipped,
        "metrics": {
            "accuracy": round(correct / len(valid), 6),
            "brier_score": round(brier, 6),
            "log_loss": round(log_loss, 6),
        },
        "by_outcome": outcomes,
        "by_competition": {key: group_summary(items) for key, items in sorted(competitions.items())},
        "by_competition_calibration": {
            key: _competition_calibration(items, seed=sum(ord(char) for char in key))
            for key, items in sorted(competitions.items())
        },
        "calibration": calibration,
        "status": "insufficient_data" if len(valid) < 30 else "descriptive_only",
        "minimum_sample_guidance": "Menos de 30 partidos: evidencia insuficiente; incluso con 30, interpretar con cautela.",
    }


@router.get("/evaluation")
def football_evaluation(
    competition: str | None = Query(None, min_length=2, max_length=8),
    model_version: str | None = Query(None, min_length=3, max_length=80),
    limit: int = Query(2000, ge=1, le=5000),
):
    """Read settled football snapshots only; does not change predictions."""
    try:
        query = (
            get_supabase_client().table("football_prediction_snapshots")
            .select("provider_match_id,competition_code,model_version,kickoff_at,home_probability,draw_probability,away_probability,actual_home_score,actual_away_score,actual_outcome,result_status,settled_at")
            .eq("result_status", "SETTLED")
            .order("kickoff_at", desc=True)
            .limit(limit)
        )
        if competition:
            query = query.eq("competition_code", competition.upper())
        # Never mix shadow experiments into official dashboard metrics.
        query = query.eq("model_version", model_version or MODEL_VERSION)
        rows = query.execute().data or []
        result = evaluate_rows(rows)
        result.update({
            "success": True,
            "read_only": True,
            "model_versions": sorted({str(r.get("model_version") or "UNKNOWN") for r in rows}),
            "competition_filter": competition.upper() if competition else None,
            "model_version_filter": model_version,
            "source": "football_prediction_snapshots",
        })
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="No fue posible leer el historial de fútbol. Verifica que la tabla football_prediction_snapshots esté creada y accesible.",
        ) from exc



@router.get("/history")
def football_prediction_history(
    competition: str | None = Query(None, min_length=2, max_length=8),
    team: str | None = Query(None, min_length=2, max_length=120),
    result_status: str | None = Query(None, alias="status", pattern="^(PENDING|SETTLED|CANCELLED)$"),
    model_version: str | None = Query(None, min_length=3, max_length=80),
    limit: int = Query(100, ge=1, le=500),
):
    """Return immutable official-model snapshots for the football history screen."""
    try:
        query = (
            get_supabase_client().table("football_prediction_snapshots")
            .select(
                "id,provider_match_id,competition_code,kickoff_at,home_team,away_team,"
                "model_version,home_probability,draw_probability,away_probability,"
                "expected_goals,prediction_payload,data_cutoff_at,created_at,"
                "result_status,actual_home_score,actual_away_score,actual_outcome,"
                "result_source,settled_at"
            )
            .order("kickoff_at", desc=True)
            .limit(limit)
        )
        if competition:
            query = query.eq("competition_code", competition.upper())
        if result_status:
            query = query.eq("result_status", result_status.upper())
        if model_version:
            query = query.eq("model_version", model_version)
        if team:
            # PostgREST OR filter searches either side without changing the stored snapshot.
            escaped = team.strip().replace(",", "\\,").replace("%", "\\%").replace("_", "\\_")
            query = query.or_(f"home_team.ilike.%{escaped}%,away_team.ilike.%{escaped}%")
        rows = query.execute().data or []
        return {
            "success": True,
            "read_only": True,
            "count": len(rows),
            "filters": {
                "competition": competition.upper() if competition else None,
                "team": team.strip() if team else None,
                "status": result_status.upper() if result_status else None,
                "model_version": model_version,
            },
            "snapshots": rows,
            "source": "football_prediction_snapshots",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="No fue posible consultar el historial persistente de fútbol.",
        ) from exc

@router.get("/evaluation/cross-league")
def football_cross_league_evaluation(
    limit_per_competition: int = Query(5000, ge=100, le=5000),
):
    """Compare official-model calibration across the five archived leagues."""
    try:
        client = get_supabase_client()
        rows_by_competition = {}
        for code in CROSS_LEAGUE_CODES:
            rows_by_competition[code] = (
                client.table("football_prediction_snapshots")
                .select("provider_match_id,competition_code,model_version,kickoff_at,home_probability,draw_probability,away_probability,actual_home_score,actual_away_score,actual_outcome,result_status,settled_at")
                .eq("result_status", "SETTLED")
                .eq("model_version", MODEL_VERSION)
                .eq("competition_code", code)
                .order("kickoff_at", desc=True)
                .limit(limit_per_competition)
                .execute().data or []
            )
        date_ranges = {
            code: sorted(
                str(row.get("kickoff_at") or "")[:10]
                for row in rows if str(row.get("kickoff_at") or "")[:10]
            )
            for code, rows in rows_by_competition.items()
        }
        populated_ranges = [dates for dates in date_ranges.values() if dates]
        common_start = max((dates[0] for dates in populated_ranges), default=None) if len(populated_ranges) == len(CROSS_LEAGUE_CODES) else None
        common_end = min((dates[-1] for dates in populated_ranges), default=None) if len(populated_ranges) == len(CROSS_LEAGUE_CODES) else None
        comparisons = {}
        for code in CROSS_LEAGUE_CODES:
            rows = rows_by_competition[code]
            if common_start and common_end and common_start <= common_end:
                rows = [
                    row for row in rows
                    if common_start <= str(row.get("kickoff_at") or "")[:10] <= common_end
                ]
            else:
                rows = []
            evaluated = evaluate_rows(rows)
            valid_items = []
            for row in rows:
                probabilities = [_number(row.get(key)) for key in (
                    "home_probability", "draw_probability", "away_probability"
                )]
                home_score = _number(row.get("actual_home_score"))
                away_score = _number(row.get("actual_away_score"))
                if (
                    any(value is None or value < 0 or value > 1 for value in probabilities)
                    or abs(sum(probabilities) - 1.0) > 0.02
                    or home_score is None or away_score is None
                    or home_score < 0 or away_score < 0
                ):
                    continue
                total = sum(probabilities)
                normalized = [value / total for value in probabilities]
                actual = "home" if home_score > away_score else "away" if home_score < away_score else "draw"
                valid_items.append((row, normalized, actual, 0))
            comparisons[code] = {
                "sample_size": evaluated["sample_size"],
                "skipped_rows": evaluated["skipped_rows"],
                "metrics": evaluated["metrics"],
                "calibration": _competition_calibration(
                    valid_items, seed=sum(ord(char) for char in code)
                ),
            }
        return {
            "success": True,
            "read_only": True,
            "source": "football_prediction_snapshots",
            "model_version": MODEL_VERSION,
            "competitions": comparisons,
            "common_date_window": {
                "date_start": common_start,
                "date_end": common_end,
                "aligned_across_all_five": bool(common_start and common_end and common_start <= common_end),
                "policy": "Las cinco ligas se filtran al intervalo calendario común dentro del límite recuperado por competición.",
            },
            "comparison_policy": {
                "scope": "Modelo oficial único; snapshots SETTLED; cada liga se evalúa por separado.",
                "minimum_matches": MIN_CROSS_LEAGUE_MATCHES,
                "minimum_independent_dates": MIN_CROSS_LEAGUE_DATES,
                "interpretation": "No ordenar ligas como mejores/peores. Comparar sesgo por resultado solo cuando cada muestra sea elegible; IC95 que cruza cero no demuestra sesgo direccional.",
                "automatic_recalibration": False,
            },
            "limit_per_competition": limit_per_competition,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="No fue posible comparar la calibración 1X2 entre las cinco ligas.",
        ) from exc

def _season_key(kickoff_at: str | None) -> str | None:
    """Approximate European season as July-June from the stored kickoff date."""
    value = str(kickoff_at or "")
    if len(value) < 7:
        return None
    try:
        year, month = int(value[:4]), int(value[5:7])
    except ValueError:
        return None
    start_year = year if month >= 7 else year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


@router.get("/evaluation/cross-league/seasons")
def football_cross_league_season_evaluation(
    limit_per_competition: int = Query(5000, ge=100, le=5000),
):
    """Describe official-model 1X2 calibration by competition and July-June season."""
    try:
        client = get_supabase_client()
        result = {}
        for code in CROSS_LEAGUE_CODES:
            rows = (
                client.table("football_prediction_snapshots")
                .select("provider_match_id,competition_code,model_version,kickoff_at,home_probability,draw_probability,away_probability,actual_home_score,actual_away_score,result_status")
                .eq("result_status", "SETTLED")
                .eq("model_version", MODEL_VERSION)
                .eq("competition_code", code)
                .order("kickoff_at", desc=True)
                .limit(limit_per_competition)
                .execute().data or []
            )
            by_season = defaultdict(list)
            skipped = 0
            for row in rows:
                season = _season_key(row.get("kickoff_at"))
                probabilities = [_number(row.get(key)) for key in (
                    "home_probability", "draw_probability", "away_probability"
                )]
                home_score = _number(row.get("actual_home_score"))
                away_score = _number(row.get("actual_away_score"))
                if (
                    season is None
                    or any(value is None or value < 0 or value > 1 for value in probabilities)
                    or abs(sum(probabilities) - 1.0) > 0.02
                    or home_score is None or away_score is None
                    or home_score < 0 or away_score < 0
                ):
                    skipped += 1
                    continue
                total = sum(probabilities)
                normalized = [value / total for value in probabilities]
                actual = "home" if home_score > away_score else "away" if home_score < away_score else "draw"
                by_season[season].append((row, normalized, actual, 0))

            seasons = {}
            for season, items in sorted(by_season.items()):
                calibration = _competition_calibration(
                    items, seed=sum(ord(char) for char in f"{code}:{season}")
                )
                n = len(items)
                brier = sum(
                    sum((p[i] - (i == actual)) ** 2 for i in range(3))
                    for _, p, _, actual in items
                ) / n
                log_loss = -sum(
                    math.log(max(1e-15, p[actual]))
                    for _, p, _, actual in items
                ) / n
                accuracy = sum(
                    max(range(3), key=lambda i: p[i]) == actual
                    for _, p, _, actual in items
                ) / n
                seasons[season] = {
                    "sample_size": n,
                    "metrics": {
                        "accuracy": round(accuracy, 6),
                        "brier_score": round(brier, 6),
                        "log_loss": round(log_loss, 6),
                    },
                    "calibration": calibration,
                }
            result[code] = {
                "season_count": len(seasons),
                "skipped_rows": skipped,
                "seasons": seasons,
            }

        return {
            "success": True,
            "read_only": True,
            "source": "football_prediction_snapshots",
            "model_version": MODEL_VERSION,
            "competitions": result,
            "season_method": "Aproximación calendario julio-junio derivada de kickoff_at; no sustituye un identificador oficial de temporada.",
            "minimum_matches": MIN_CROSS_LEAGUE_MATCHES,
            "minimum_independent_dates": MIN_CROSS_LEAGUE_DATES,
            "interpretation": "Cada temporada se evalúa dentro de su liga. Las muestras no elegibles se muestran, pero no permiten conclusiones comparativas. No se ajusta el modelo.",
            "automatic_recalibration": False,
            "limit_per_competition": limit_per_competition,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="No fue posible evaluar la estabilidad estacional de la calibración 1X2.",
        ) from exc
