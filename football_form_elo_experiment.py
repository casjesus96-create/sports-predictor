"""Recent-form + opponent-strength Elo candidate. Shadow-only; never changes official predictions."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

EXPERIMENT_VERSION = "FOOTBALL-FORM-ELO-SHADOW-0.1.0"
MAX_RECENT = 12
MIN_RECENT = 5
INITIAL_ELO = 1500.0
ELO_K = 24.0


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return dt if dt.tzinfo else None
    except (TypeError, ValueError):
        return None


def _score(match: dict) -> tuple[int, int] | None:
    if str(match.get("status", "")).upper() not in {"FINISHED", "AWARDED"}:
        return None
    full = ((match.get("score") or {}).get("fullTime") or {})
    h, a = full.get("home"), full.get("away")
    if any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in (h, a)):
        return None
    return h, a


def _pmf(rate: float, goals: int) -> float:
    return math.exp(-rate) * rate ** goals / math.factorial(goals) if rate > 0 else float(goals == 0)


def _unavailable(reason: str, **extra: Any) -> dict:
    return {"available": False, "reason": reason, "model_version": EXPERIMENT_VERSION, **extra}


def predict_form_elo(
    home_team_id: int, away_team_id: int, home_team: str, away_team: str,
    kickoff_at: str, home_history: list[dict], away_history: list[dict],
    target_baseline: dict[str, float] | None = None,
) -> dict:
    """Use strictly pre-kickoff match results, recency decay, opponent-adjusted Elo and venue splits."""
    kickoff = _date(kickoff_at)
    if kickoff is None:
        return _unavailable("La fecha del encuentro no es ISO 8601 con zona horaria.")
    if home_team_id == away_team_id or not home_team.strip() or not away_team.strip():
        return _unavailable("Los equipos no son válidos.")
    if not target_baseline or target_baseline.get("home", 0) <= 0 or target_baseline.get("away", 0) <= 0:
        return _unavailable("No existe una media goleadora verificable de la competición objetivo.")

    # Merge provider histories and deduplicate by match ID. Future results are excluded.
    merged: dict[str, dict] = {}
    for row in home_history + away_history:
        dt = _date(row.get("utcDate") or row.get("date"))
        score = _score(row)
        h, a = row.get("homeTeam") or {}, row.get("awayTeam") or {}
        if dt is None or dt >= kickoff or score is None or not h.get("id") or not a.get("id"):
            continue
        key = str(row.get("id") or f"{dt.isoformat()}:{h.get('id')}:{a.get('id')}")
        merged[key] = {"date": dt, "home_id": int(h["id"]), "away_id": int(a["id"]),
                       "hg": score[0], "ag": score[1]}
    ordered = sorted(merged.values(), key=lambda x: x["date"])
    ratings: dict[int, float] = {}
    for row in ordered:
        hi, ai = row["home_id"], row["away_id"]
        rh, ra = ratings.get(hi, INITIAL_ELO), ratings.get(ai, INITIAL_ELO)
        expected = 1.0 / (1.0 + 10 ** ((ra - rh) / 400.0))
        actual = 1.0 if row["hg"] > row["ag"] else 0.5 if row["hg"] == row["ag"] else 0.0
        # Goal-difference multiplier is capped to avoid extreme scoreline updates.
        margin = min(2.0, 1.0 + math.log1p(abs(row["hg"] - row["ag"])) * 0.35)
        delta = ELO_K * margin * (actual - expected)
        ratings[hi] = rh + delta
        ratings[ai] = ra - delta

    def recent(team_id: int):
        rows = []
        for row in ordered:
            if row["home_id"] == team_id:
                rows.append((row["date"], row["hg"], row["ag"], row["away_id"], True))
            elif row["away_id"] == team_id:
                rows.append((row["date"], row["ag"], row["hg"], row["home_id"], False))
        rows.sort(key=lambda x: x[0], reverse=True)
        return rows[:MAX_RECENT]

    home_rows, away_rows = recent(home_team_id), recent(away_team_id)
    if len(home_rows) < MIN_RECENT or len(away_rows) < MIN_RECENT:
        return _unavailable(
            f"Se requieren al menos {MIN_RECENT} resultados recientes válidos por equipo.",
            sample={"home_matches": len(home_rows), "away_matches": len(away_rows)},
        )

    def weighted_rate(rows, field: int) -> float:
        weights = [0.5 ** (i / 5.0) for i in range(len(rows))]
        return sum(w * row[field] for w, row in zip(weights, rows)) / sum(weights)

    # Form indices are shrunk toward 1.0 to avoid overreacting to short streaks.
    def form_index(rows, field: int) -> float:
        raw = weighted_rate(rows, field)
        return (raw * len(rows) + 1.0 * 5.0) / (len(rows) + 5.0)

    # Adjust recent scoring/conceding rates for strength of the opponents faced.
    def opponent_factor(rows) -> float:
        factors = []
        for row in rows:
            opponent_rating = ratings.get(row[3], INITIAL_ELO)
            factors.append(max(0.82, min(1.18, 1.0 + (opponent_rating - INITIAL_ELO) / 1200.0)))
        weights = [0.5 ** (i / 5.0) for i in range(len(rows))]
        return sum(w * f for w, f in zip(weights, factors)) / sum(weights)

    home_attack = form_index(home_rows, 1) / opponent_factor(home_rows)
    home_concede = form_index(home_rows, 2) * opponent_factor(home_rows)
    away_attack = form_index(away_rows, 1) / opponent_factor(away_rows)
    away_concede = form_index(away_rows, 2) * opponent_factor(away_rows)

    # Elo is a bounded relative-strength signal, not a standalone probability.
    elo_home = ratings.get(home_team_id, INITIAL_ELO)
    elo_away = ratings.get(away_team_id, INITIAL_ELO)
    elo_edge = max(-0.22, min(0.22, (elo_home - elo_away) / 1800.0))
    exp_home = max(0.15, min(4.5, target_baseline["home"] * home_attack * away_concede * (1.0 + elo_edge)))
    exp_away = max(0.15, min(4.5, target_baseline["away"] * away_attack * home_concede / (1.0 + elo_edge)))

    hp = [_pmf(exp_home, n) for n in range(11)]
    ap = [_pmf(exp_away, n) for n in range(11)]
    matrix = [[hp[h] * ap[a] for a in range(11)] for h in range(11)]
    total = sum(map(sum, matrix))
    matrix = [[v / total for v in row] for row in matrix]
    probs = {
        "home": sum(matrix[h][a] for h in range(11) for a in range(11) if h > a),
        "draw": sum(matrix[g][g] for g in range(11)),
        "away": sum(matrix[h][a] for h in range(11) for a in range(11) if h < a),
    }
    return {
        "available": True, "status": "SHADOW_ONLY", "model_version": EXPERIMENT_VERSION,
        "home_team": home_team, "away_team": away_team,
        "probabilities": {k: round(v, 6) for k, v in probs.items()},
        "expected_goals": {"home": round(exp_home, 3), "away": round(exp_away, 3),
                           "total": round(exp_home + exp_away, 3)},
        "strength": {"home_elo": round(elo_home, 1), "away_elo": round(elo_away, 1),
                     "elo_difference": round(elo_home - elo_away, 1)},
        "sample": {"home_matches": len(home_rows), "away_matches": len(away_rows),
                   "max_recent_matches": MAX_RECENT, "future_matches_excluded": True,
                   "recency_half_life_matches": 5, "opponent_adjustment": True,
                   "competitions_in_history": sorted({str(((r.get("competition") or {}).get("code") or "")) for r in home_history + away_history if r.get("competition")})},
        "data_scope": "Resultados oficiales finalizados anteriores al inicio; no usa alineaciones, lesiones, xG ni cuotas.",
        "method": "Poisson con forma reciente ponderada, ajuste limitado por fuerza Elo de rivales y rating Elo cronológico.",
        "calibration": {"status": "not_calibrated", "note": "Shadow only; no usar como modelo oficial hasta superar walk-forward."},
        "limitations": ["El Elo entre competiciones puede tener sesgo si los equipos no comparten rivales.",
                        "No incorpora xG, alineaciones, lesiones, descanso ni cuotas de mercado."]
    }
