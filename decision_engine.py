""""Transparent calculations for the Sports Predictor decision center.

The engine does not generate a prediction. It compares user-supplied probabilities
and decimal odds, optionally estimates a no-vig market probability from both sides,
and reports consistency checks. No outcome is guaranteed.
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
    opponent_model_probability: float | None = None,
    opponent_decimal_odds: float | None = None,
) -> dict:
    sport = str(sport).upper().strip()
    if sport not in VALID_SPORTS:
        raise ValueError("sport debe ser MLB, NFL, NBA o TENNIS.")
    if not 0 < float(model_probability) < 1:
        raise ValueError("model_probability debe estar entre 0 y 1, sin incluir extremos.")
    if not 1 < float(decimal_odds) <= 1000:
        raise ValueError("decimal_odds debe ser mayor que 1 y como máximo 1000.")
    if not 0 <= int(data_quality) <= 100:
        raise ValueError("data_quality debe estar entre 0 y 100.")
    if market_probability is not None and not 0 < float(market_probability) < 1:
        raise ValueError("market_probability debe estar entre 0 y 1, sin incluir extremos.")
    if opponent_model_probability is not None and not 0 < float(opponent_model_probability) < 1:
        raise ValueError("opponent_model_probability debe estar entre 0 y 1, sin incluir extremos.")
    if opponent_decimal_odds is not None and not 1 < float(opponent_decimal_odds) <= 1000:
        raise ValueError("opponent_decimal_odds debe ser mayor que 1 y como máximo 1000.")

    probability = float(model_probability)
    odds = float(decimal_odds)
    implied_probability = 1.0 / odds
    fair_odds = 1.0 / probability
    expected_value = probability * odds - 1.0
    edge = probability - implied_probability
    signals = list(dict.fromkeys(str(s).strip() for s in risk_signals if str(s).strip()))
    quality = int(data_quality)

    opponent_probability = float(opponent_model_probability) if opponent_model_probability is not None else None
    probability_pair_sum = probability + opponent_probability if opponent_probability is not None else None
    probability_pair_consistent = (
        abs(probability_pair_sum - 1.0) <= 0.01 if probability_pair_sum is not None else None
    )

    opponent_odds = float(opponent_decimal_odds) if opponent_decimal_odds is not None else None
    opponent_implied = 1.0 / opponent_odds if opponent_odds is not None else None
    implied_total = implied_probability + opponent_implied if opponent_implied is not None else None
    overround_percentage = (implied_total - 1.0) * 100 if implied_total is not None else None
    calculated_no_vig_probability = (
        implied_probability / implied_total if implied_total and implied_total > 0 else None
    )

    # Prefer a manually supplied, already de-vigged probability. Otherwise,
    # normalize the two sides' raw implied probabilities when both odds exist.
    comparison_market_probability = (
        float(market_probability)
        if market_probability is not None
        else calculated_no_vig_probability
    )
    market_gap = (
        probability - comparison_market_probability
        if comparison_market_probability is not None
        else None
    )

    upset_candidate = (
        implied_probability < 0.50
        and market_gap is not None
        and market_gap >= 0.05
        and expected_value > 0
        and quality >= 70
        and not signals
    )

    # Keep the decision conservative, but explain the exact blocking condition.
    if quality < 50:
        classification = "NO_PLAY"
        label = "Sin ventaja demostrable: calidad de datos insuficiente"
        classification_reason = (
            f"La calidad de datos es {quality}/100; se requieren al menos 50/100 "
            "para evaluar una oportunidad."
        )
    elif expected_value <= 0:
        classification = "NO_PLAY"
        label = "Sin ventaja demostrable: valor esperado no positivo"
        classification_reason = (
            "El valor esperado teórico no es positivo con la probabilidad y cuota introducidas."
        )
    elif upset_candidate:
        classification = "UPSET_CANDIDATE"
        label = "Posible sorpresa: validar"
        classification_reason = (
            "Existe una diferencia relevante frente al mercado y valor esperado positivo; "
            "requiere validación, no garantiza un resultado."
        )
    elif signals or quality < 75:
        classification = "HIGH_RISK"
        label = "Riesgo elevado / posible partido trampa"
        classification_reason = (
            "Hay señales de riesgo o la calidad de datos es inferior al umbral recomendado de 75/100."
        )
    elif expected_value >= 0.03:
        classification = "VALUE_CANDIDATE"
        label = "Candidata con valor teórico"
        classification_reason = (
            "El valor esperado teórico es al menos 3%, con calidad de datos suficiente y sin señales de riesgo registradas."
        )
    else:
        classification = "MARGINAL"
        label = "Ventaja pequeña; no priorizar"
        classification_reason = (
            "El valor esperado teórico es positivo, pero inferior al umbral del 3%."
        )

    warnings = []
    if signals:
        warnings.append("Hay señales de riesgo que requieren revisión.")
    if quality < 75:
        warnings.append("La calidad de datos no alcanza el umbral recomendado de 75/100.")
    if quality < 50:
        warnings.append(
            "La evaluación queda bloqueada por calidad de datos inferior a 50/100; "
            "un valor esperado positivo no basta para demostrar ventaja."
        )
    if market_probability is None and opponent_odds is None:
        warnings.append("No se aportó una probabilidad de mercado sin margen ni la cuota del rival; la comparación usa la probabilidad implícita bruta de esta cuota.")
    elif market_probability is None and opponent_odds is not None:
        warnings.append("La probabilidad de mercado sin margen se estima normalizando las probabilidades implícitas de ambas cuotas; es una aproximación.")
    if probability_pair_consistent is False:
        warnings.append("Las probabilidades introducidas para ambos equipos no suman aproximadamente 100%; revisa que correspondan al mismo partido y mercado.")
    if classification == "UPSET_CANDIDATE":
        warnings.append("La etiqueta identifica una posible discrepancia, no garantiza una sorpresa.")
    if expected_value > 0:
        warnings.append("El valor esperado depende de que la probabilidad del modelo esté bien calibrada.")

    return {
        "success": True,
        "sport": sport,
        "classification": classification,
        "label": label,
        "classification_reason": classification_reason,
        "model_probability": round(probability, 6),
        "decimal_odds": round(odds, 4),
        "implied_probability": round(implied_probability, 6),
        "fair_odds": round(fair_odds, 4),
        "edge_percentage_points": round(edge * 100, 3),
        "expected_value_percent": round(expected_value * 100, 3),
        "data_quality": quality,
        "risk_signals": signals,
        "market_probability": round(float(market_probability), 6) if market_probability is not None else None,
        "calculated_no_vig_market_probability": round(calculated_no_vig_probability, 6) if calculated_no_vig_probability is not None else None,
        "market_comparison_probability": round(comparison_market_probability, 6) if comparison_market_probability is not None else None,
        "model_market_gap_percentage_points": round(market_gap * 100, 3) if market_gap is not None else None,
        "opponent_model_probability": round(opponent_probability, 6) if opponent_probability is not None else None,
        "model_probability_pair_sum": round(probability_pair_sum, 6) if probability_pair_sum is not None else None,
        "model_probabilities_consistent": probability_pair_consistent,
        "opponent_decimal_odds": round(opponent_odds, 4) if opponent_odds is not None else None,
        "opponent_implied_probability": round(opponent_implied, 6) if opponent_implied is not None else None,
        "market_implied_total": round(implied_total, 6) if implied_total is not None else None,
        "market_overround_percentage": round(overround_percentage, 3) if overround_percentage is not None else None,
        "warnings": warnings,
        "is_guaranteed": False,
        "basis": "Cálculo matemático con probabilidades introducidas; no es una predicción independiente ni una garantía.",
    }
