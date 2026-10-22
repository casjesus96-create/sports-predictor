"""Read-only calibration summaries for settled prediction snapshots."""
from __future__ import annotations

import math

SPORT_ALIASES = {
    "BASEBALL": "MLB", "MLB": "MLB",
    "AMERICAN FOOTBALL": "NFL", "FOOTBALL": "NFL", "NFL": "NFL",
    "BASKETBALL": "NBA", "NBA": "NBA", "TENNIS": "TENNIS",
}
OFFICIAL_VERSIONS = {
    "MLB": {"2.0.0-matchup"},
    "NBA": {"NBA-1.1.0"},
    "NFL": {"NFL-1.0.0"},
    "TENNIS": {"TENNIS-ELO-1.0.0"},
}


def _sport(row: dict) -> str:
    raw = str(row.get("league") or row.get("sport") or "").strip().upper()
    return SPORT_ALIASES.get(raw, raw)


def build_calibration_report(rows: list[dict]) -> dict:
    """Bin settled home-win probabilities by decile and compare with outcomes.

    Tied games, malformed scores/probabilities, unknown sports, and snapshots
    whose home/away probabilities do not sum to approximately 1 are excluded.
    Each bin's observed rate is descriptive, not proof of calibration.
    """
    groups: dict[tuple[str, str], dict] = {}
    excluded = 0
    for row in rows:
        try:
            home_p = float(row.get("home_probability"))
            away_p = float(row.get("away_probability"))
            home_score = float(row.get("actual_home_score"))
            away_score = float(row.get("actual_away_score"))
            if not all(math.isfinite(x) for x in (home_p, away_p, home_score, away_score)):
                raise ValueError("non-finite value")
            if not (0 < home_p < 1 and 0 < away_p < 1):
                raise ValueError("invalid probability")
            if abs(home_p + away_p - 1.0) > 0.02 or home_score == away_score:
                raise ValueError("inconsistent probabilities or tied result")
        except (TypeError, ValueError):
            excluded += 1
            continue

        sport = _sport(row)
        if sport not in OFFICIAL_VERSIONS:
            excluded += 1
            continue
        model = str(row.get("model_version") or "unknown")
        status = "OFFICIAL" if model in OFFICIAL_VERSIONS[sport] else "HISTORICAL"
        key = (sport, model)
        group = groups.setdefault(key, {
            "sport": sport,
            "model_version": model,
            "model_status": status,
            "sample_size": 0,
            "brier_total": 0.0,
            "log_loss_total": 0.0,
            "bins": {},
        })
        outcome = 1 if home_score > away_score else 0
        bin_index = min(int(home_p * 10), 9)
        bucket = group["bins"].setdefault(bin_index, {
            "bin_lower": bin_index / 10,
            "bin_upper": (bin_index + 1) / 10,
            "sample_size": 0,
            "predicted_probability_total": 0.0,
            "home_wins": 0,
        })
        bucket["sample_size"] += 1
        bucket["predicted_probability_total"] += home_p
        bucket["home_wins"] += outcome
        group["sample_size"] += 1
        group["brier_total"] += (home_p - outcome) ** 2
        clipped = min(max(home_p, 1e-15), 1 - 1e-15)
        group["log_loss_total"] += -math.log(clipped if outcome else 1 - clipped)

    results = []
    for group in groups.values():
        n = group["sample_size"]
        bins = []
        for index in sorted(group["bins"]):
            bucket = group["bins"][index]
            count = bucket["sample_size"]
            predicted = bucket["predicted_probability_total"] / count
            observed = bucket["home_wins"] / count
            bins.append({
                "range": f'{bucket["bin_lower"]:.0%}-{bucket["bin_upper"]:.0%}',
                "bin_lower": bucket["bin_lower"],
                "bin_upper": bucket["bin_upper"],
                "sample_size": count,
                "mean_predicted_probability": round(predicted, 4),
                "observed_home_win_rate": round(observed, 4),
                "calibration_gap_percentage_points": round((observed - predicted) * 100, 2),
                "small_sample": count < 20,
            })
        results.append({
            "sport": group["sport"],
            "model_version": group["model_version"],
            "model_status": group["model_status"],
            "sample_size": n,
            "brier_score_home": round(group["brier_total"] / n, 6),
            "log_loss_home": round(group["log_loss_total"] / n, 6),
            "bins": bins,
            "sample_warning": (
                "Muestra pequeña; no concluir ni ajustar el modelo con estos datos."
                if n < 30 else None
            ),
        })
    results.sort(key=lambda item: (item["sport"], item["model_version"]))
    return {
        "groups": results,
        "settled_rows_excluded": excluded,
        "methodology": {
            "calibration": "Compara la probabilidad media de victoria local con la frecuencia observada por intervalos del 10%.",
            "gap": "Frecuencia observada menos probabilidad media; valores positivos indican subestimación de victorias locales.",
            "brier_score_home": "Menor es mejor; error cuadrático de la probabilidad local.",
            "log_loss_home": "Menor es mejor; penaliza con fuerza probabilidades muy seguras que fallan.",
            "minimum_sample_warning": "Los intervalos con menos de 20 partidos y grupos con menos de 30 se marcan como muestra pequeña.",
            "limitations": "Es una auditoría retrospectiva descriptiva; no cambia predicciones ni demuestra rentabilidad.",
        },
    }
