"""Cross-sport market catalog and transparent projection adapters.

This module never changes official winner probabilities or writes prediction history.
Only projections backed by saved pregame data are returned; missing inputs stay unavailable.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

SPORT_ALIASES = {
    "BASEBALL": "MLB", "MLB": "MLB", "BASKETBALL": "NBA", "NBA": "NBA",
    "AMERICAN FOOTBALL": "NFL", "NFL": "NFL", "FOOTBALL": "FOOTBALL",
    "SOCCER": "FOOTBALL", "TENNIS": "TENNIS",
}

CATALOG = {
    "MLB": [
        ("winner", "Ganador del encuentro", "available", "Probabilidad del modelo oficial MLB."),
        ("run_total", "Total de carreras", "experimental", "Distribución Poisson aproximada a partir de carreras esperadas; requiere backtest."),
        ("run_margin", "Margen de carreras (1+, 2+, 3+)", "experimental", "Diferencia de dos distribuciones Poisson independientes; requiere backtest."),
        ("pitcher_strikeouts", "Ponches del abridor", "experimental", "Usa la proyección existente de K/9 e innings estimados; requiere backtest."),
        ("batter_hits", "Hits por bateador", "unavailable", "No existe todavía un modelo individual validado de probabilidad de hit."),
    ],
    "NBA": [
        ("winner", "Ganador del encuentro", "available", "Probabilidad del modelo oficial NBA."),
        ("team_points", "Puntos por equipo", "experimental", "Proyección de puntos existente; no equivale a probabilidad calibrada de superar una línea."),
        ("point_margin", "Margen de puntos", "experimental", "La proyección de marcador es descriptiva; la probabilidad de margen requiere validación."),
        ("player_points", "Puntos por jugador", "experimental", "Se muestran solo proyecciones individuales guardadas; no se inventan probabilidades por umbral."),
        ("player_rebounds", "Rebotes por jugador", "experimental", "Depende de la cobertura de boxscores históricos y del módulo de proyección."),
        ("player_assists", "Asistencias por jugador", "experimental", "Depende de la cobertura de boxscores históricos y del módulo de proyección."),
    ],
    "NFL": [
        ("winner", "Ganador del encuentro", "available", "Probabilidad del modelo oficial NFL."),
        ("team_points", "Puntos por equipo y total", "experimental", "Proyección de marcador existente; baseline no calibrado."),
        ("point_margin", "Margen de puntos", "experimental", "Proyección descriptiva; no se presenta como probabilidad calibrada."),
        ("player_props", "Yardas, recepciones y touchdowns", "unavailable", "No hay todavía un modelo individual pregame conectado y validado para estos mercados."),
    ],
    "FOOTBALL": [
        ("winner_1x2", "Victoria, empate o derrota", "experimental", "El modelo de goles 1X2 sigue en validación y no se trata como modelo oficial activo."),
        ("goal_total", "Total de goles", "experimental", "Solo se muestra si el snapshot guardó tasas de goles; requiere validación."),
        ("player_props", "Goles, tiros y tiros a puerta", "unavailable", "Faltan proyecciones individuales pregame validadas."),
    ],
    "TENNIS": [
        ("winner", "Ganador del partido", "experimental", "Elo general continúa como modelo candidato, no oficial de producción."),
        ("set_winner", "Ganador de cada set", "unavailable", "No existe aún una distribución por sets validada."),
        ("aces", "Aces y dobles faltas", "unavailable", "Falta un modelo individual por jugador y partido."),
    ],
}


def normalize_sport(row: dict) -> str:
    raw = str(row.get("league") or row.get("sport") or "").strip().upper()
    return SPORT_ALIASES.get(raw, raw)


def _finite(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _poisson_pmf(k: int, lam: float) -> float:
    if k < 0 or lam < 0:
        return 0.0
    if lam == 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def poisson_at_least(threshold: int, mean: float) -> float | None:
    if threshold < 0 or mean < 0 or not math.isfinite(mean):
        return None
    return min(1.0, max(0.0, 1.0 - sum(_poisson_pmf(k, mean) for k in range(threshold))))


def poisson_margin_probability(home_mean: float, away_mean: float, margin: int) -> float:
    """P(home wins by at least margin) under independent Poisson score counts."""
    limit = max(30, int(max(home_mean, away_mean) + 12 * math.sqrt(max(home_mean, away_mean, 1)) + 15))
    probability = 0.0
    for home_score in range(limit + 1):
        p_home = _poisson_pmf(home_score, home_mean)
        for away_score in range(max(0, home_score - margin + 1)):
            probability += p_home * _poisson_pmf(away_score, away_mean)
    return min(1.0, max(0.0, probability))


def _market(market_id, label, value=None, probability=None, status="unavailable", note=""):
    return {
        "market_id": market_id,
        "label": label,
        "value": value,
        "probability": round(probability, 6) if probability is not None else None,
        "probability_percent": round(probability * 100, 2) if probability is not None else None,
        "status": status,
        "note": note,
    }


def project_snapshot(row: dict) -> dict:
    sport = normalize_sport(row)
    features = row.get("features") or {}
    factors = features.get("factors") or {}
    projections = features.get("projections") or {}
    home = str((features.get("game") or {}).get("home") or row.get("home_team") or "Local")
    away = str((features.get("game") or {}).get("away") or row.get("away_team") or "Visitante")
    home_p, away_p = _finite(row.get("home_probability")), _finite(row.get("away_probability"))
    markets = []

    if home_p is not None and away_p is not None and abs(home_p + away_p - 1) <= 0.03:
        winner_status = "experimental" if sport in {"FOOTBALL", "TENNIS"} else "available"
        markets.extend([
            _market("home_win", f"Gana {home}", probability=home_p, status=winner_status,
                    note="Probabilidad del snapshot pregame guardado; no modificada por este módulo."),
            _market("away_win", f"Gana {away}", probability=away_p, status=winner_status,
                    note="Probabilidad del snapshot pregame guardado; no modificada por este módulo."),
        ])
    else:
        markets.append(_market("winner", "Ganador", note="El snapshot no contiene probabilidades válidas."))

    if sport == "MLB":
        run = factors.get("run_projection") or {}
        home_run = _finite((run.get("home") or {}).get("expected_runs"))
        away_run = _finite((run.get("away") or {}).get("expected_runs"))
        if home_run is not None and away_run is not None:
            total = home_run + away_run
            markets.append(_market("projected_runs", "Carreras esperadas (local - visitante)",
                                   value={"home": home_run, "away": away_run, "total": round(total, 2)},
                                   status="experimental", note=run.get("note") or "Proyección descriptiva de carreras."))
            for line in (5, 6, 7, 8, 9, 10):
                p_over = 1.0 - sum(
                    _poisson_pmf(h, home_run) * _poisson_pmf(a, away_run)
                    for h in range(31) for a in range(31) if h + a <= line
                )
                markets.append(_market(f"runs_over_{line}", f"Más de {line} carreras",
                                       probability=p_over, status="experimental",
                                       note="Aproximación Poisson independiente; no validada históricamente."))
            for margin in (1, 2, 3):
                markets.append(_market(f"home_margin_{margin}", f"{home} gana por {margin}+ carreras",
                                       probability=poisson_margin_probability(home_run, away_run, margin),
                                       status="experimental", note="Aproximación Poisson independiente; no validada históricamente."))
                markets.append(_market(f"away_margin_{margin}", f"{away} gana por {margin}+ carreras",
                                       probability=poisson_margin_probability(away_run, home_run, margin),
                                       status="experimental", note="Aproximación Poisson independiente; no validada históricamente."))
        ks = factors.get("pitcher_strikeout_projection") or {}
        for side in ("home_pitcher", "away_pitcher"):
            pitcher = ks.get(side) or {}
            name = pitcher.get("pitcher_name")
            for threshold in (5, 6, 7):
                probability = _finite(pitcher.get(f"probability_{threshold}_plus"))
                if name and probability is not None:
                    markets.append(_market(f"{side}_ks_{threshold}", f"{name}: {threshold}+ ponches",
                                           probability=probability, status="experimental",
                                           note=pitcher.get("method") or "Estimación no validada."))
        markets.append(_market("batter_hit", "Bateador consigue 1+ hit", status="unavailable",
                               note="Falta una probabilidad individual pregame validada; no se infiere solo por estar en el lineup."))
    elif sport == "NBA":
        home_history = factors.get("home_history") or {}
        away_history = factors.get("away_history") or {}
        home_points = _finite(projections.get("projected_home_points"))
        away_points = _finite(projections.get("projected_away_points"))
        if home_points is None:
            home_points = _finite(projections.get("home_points"))
        if away_points is None:
            away_points = _finite(projections.get("away_points"))
        if away_points is None:
            away_points = _finite(projections.get("away_points"))

        if home_points is not None and away_points is not None:
            markets.append(_market("projected_points", "Puntos esperados (local - visitante)",
                                   value={"home": home_points, "away": away_points, "total": round(home_points + away_points, 2),
                                          "margin_home": round(home_points - away_points, 2)},
                                   status="experimental", note="Estimación de marcador guardada; no es una probabilidad de línea."))
        player_data = projections.get("player_projections") or {}
        player_rows = []
        for team in player_data.get("teams", []) if isinstance(player_data, dict) else []:
            for player in team.get("players", []) or []:
                player_rows.append(player)
        if isinstance(player_data, list):
            player_rows.extend(player_data)
        if player_rows:
            for player in player_rows[:60]:
                if not isinstance(player, dict):
                    continue
                name = player.get("player_name") or player.get("name")
                available_stats = {
                    "points": _finite(player.get("projected_points", player.get("points"))),
                    "rebounds": _finite(player.get("projected_rebounds", player.get("rebounds"))),
                    "assists": _finite(player.get("projected_assists", player.get("assists"))),
                    "steals": _finite(player.get("projected_steals", player.get("steals"))),
                    "blocks": _finite(player.get("projected_blocks", player.get("blocks"))),
                }
                available_stats = {key: val for key, val in available_stats.items() if val is not None}
                if name and available_stats:
                    markets.append(_market("player_stats", f"{name}: proyección individual", value=available_stats,
                                           status="experimental", note="Promedio de partidos anteriores; no ajusta aún por minutos/lesiones y no equivale a probabilidad de superar una línea."))
        if not any(m["market_id"] == "player_stats" for m in markets):
            markets.append(_market("player_stats", "Puntos, rebotes y asistencias por jugador",
                                   status="unavailable", note="No hay proyecciones individuales utilizables en este snapshot."))
    elif sport == "NFL":
        score = factors.get("score_projection") or {}
        if score.get("available"):
            markets.append(_market("projected_points", "Puntos esperados (local - visitante)",
                                   value={"home": score.get("projected_home_points"),
                                          "away": score.get("projected_away_points"),
                                          "total": score.get("projected_total_points"),
                                          "margin_home": score.get("projected_home_margin")},
                                   status="experimental", note="Baseline de marcador no calibrado; spread/total del mercado no son necesarios."))
        else:
            markets.append(_market("projected_points", "Puntos esperados", status="unavailable",
                                   note=score.get("reason") or "No hay proyección de puntos guardada."))
        markets.append(_market("player_props", "Yardas, recepciones y touchdowns por jugador",
                               status="unavailable", note="No hay un modelo individual pregame conectado para este snapshot."))
    elif sport == "FOOTBALL":
        probs = row.get("prediction_payload") or {}
        markets.append(_market("draw", "Empate", probability=_finite(row.get("draw_probability")),
                               status="experimental", note="Modelo 1X2 candidato; no oficial de producción."))
        expected = row.get("expected_goals") or probs.get("expected_goals") or {}
        if expected:
            markets.append(_market("expected_goals", "Goles esperados", value=expected, status="experimental",
                                   note="Proyección guardada; modelo candidato en validación."))
        else:
            markets.append(_market("expected_goals", "Goles esperados", status="unavailable",
                                   note="El snapshot no contiene goles esperados."))
    elif sport == "TENNIS":
        markets.append(_market("set_markets", "Ganador de set / juegos / aces", status="unavailable",
                               note="El Elo guardado solo estima ganador del partido; no se extrapola a otros mercados."))
    return {
        "snapshot_id": str(row.get("id") or ""),
        "event_id": str(row.get("event_id") or row.get("provider_match_id") or row.get("match_id") or ""),
        "sport": sport,
        "model_version": row.get("model_version"),
        "created_at": row.get("created_at") or row.get("data_cutoff_at"),
        "home": home,
        "away": away,
        "data_quality": row.get("data_quality"),
        "markets": markets,
    }


def catalog_for(sport: str | None = None) -> dict:
    if sport:
        key = SPORT_ALIASES.get(sport.strip().upper(), sport.strip().upper())
        return {"sport": key, "markets": [
            {"market_id": market_id, "label": label, "status": status, "description": description}
            for market_id, label, status, description in CATALOG.get(key, [])
        ]}
    return {"sports": {
        key: [{"market_id": mid, "label": label, "status": status, "description": desc}
              for mid, label, status, desc in markets]
        for key, markets in CATALOG.items()
    }}
