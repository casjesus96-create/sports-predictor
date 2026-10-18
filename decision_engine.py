"""Transparent, deterministic decision-support calculations.

This module does not predict game outcomes. It compares a supplied model
probability with decimal odds and flags missing/uncertain inputs. Historical
calibration and market de-vigging are deliberately not inferred here.
"""
from __future__ import annotations

from typing import Iterable


VALID_SPORTS = {"MLB", "NFL", "NBA", "TENNIS"}


def evaluate_decision(
    *,
    sport: str,
    model_probability: float,
    decimal_odds: float,
    data_quality: int = 100,
    risk_signals: Iterable[str] = (),
    market_probability: float | None = None,
) -> dict:
    sport = str(sport).upper().strip()
    if sport not in VALID_SPORTS:
        raise ValueError("sport debe ser MLB, NFL, NBA o TENNIS.")
    if not 0 < float(model_probability) < 1:
        raise ValueError("model_probability debe estar entre 0 y 1, sin incluir extremos.")
    if float(decimal_odds) <= 1:
        raise ValueError("decimal_odds debe ser mayor que 1.")
    if not 0 <= int(data_quality) <= 100:
        raise ValueError("data_quality debe estar entre 0 y 100.")
    if market_probability is not None and not 0 < float(market_probability) < 1:
        raise ValueError("market_probability debe estar entre 0 y 1, sin incluir extremos.")

    probability = float(model_probability)
    odds = float(decimal_odds)
    implied_probability = 1.0 / odds
    fair_odds = 1.0 / probability
    expected_value = probability * odds - 1.0
    edge = probability - implied_probability
    signals = list(dict.fromkeys(str(s).strip() for s in risk_signals if str(s).strip()))
    quality = int(data_quality)

    if market_probability is not None:
        market_gap = probability - float(market_probability)
    else:
        market_gap = None

    # A potential upset is a market underdog with a meaningful model/market gap.
    upset_candidate = (
        implied_probability < 0.50
        and market_gap is not None
        and market_gap >= 0.05
        and expected_value > 0
        and quality >= 70
        and not signals
    )

    if expected_value <= 0 or quality < 50:
        classification = "NO_PLAY"
        label = "Sin ventaja demostrable"
    elif upset_candidate:
        classification = "UPSET_CANDIDATE"
        label = "Posible sorpresa: validar"
    elif signals or quality < 75:
        classification = "HIGH_RISK"
        label = "Riesgo elevado / posible partido trampa"
    elif expected_value >= 0.03:
        classification = "VALUE_CANDIDATE"
        label = "Candidata con valor teórico"
    else:
        classification = "MARGINAL"
        label = "Ventaja pequeña; no priorizar"

    warnings = []
    if signals:
        warnings.append("Hay señales de riesgo que requieren revisión.")
    if quality < 75:
        warnings.append("La calidad de datos no alcanza el umbral recomendado de 75/100.")
    if market_probability is None:
        warnings.append("No se aportó una probabilidad de mercado sin margen; la comparación usa la probabilidad implícita bruta de la cuota.")
    if classification == "UPSET_CANDIDATE":
        warnings.append("La etiqueta identifica una posible discrepancia, no garantiza una sorpresa.")
    if expected_value > 0:
        warnings.append("El valor esperado depende de que la probabilidad del modelo esté bien calibrada.")

    return {
        "success": True,
        "sport": sport,
        "classification": classification,
        "label": label,
        "model_probability": round(probability, 6),
        "decimal_odds": round(odds, 4),
        "implied_probability": round(implied_probability, 6),
        "fair_odds": round(fair_odds, 4),
        "edge_percentage_points": round(edge * 100, 3),
        "expected_value_percent": round(expected_value * 100, 3),
        "data_quality": quality,
        "risk_signals": signals,
        "market_probability": round(float(market_probability), 6) if market_probability is not None else None,
        "model_market_gap_percentage_points": round(market_gap * 100, 3) if market_gap is not None else None,
        "warnings": warnings,
        "is_guaranteed": False,
        "basis": "Cálculo matemático con probabilidades introducidas; no es una predicción independiente ni una garantía.",
    }
