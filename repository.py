import os
from datetime import datetime, timezone

from supabase import create_client


def get_supabase_client():
    """
    Crea y devuelve el cliente de Supabase.
    """

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")

    if not url or not key:
        return None

    return create_client(url, key)


def save_prediction(payload):
    """
    Guarda una predicción nueva en prediction_snapshots.
    """

    client = get_supabase_client()

    if client is None:
        return {
            "persisted": False,
            "reason": "Supabase variables not configured"
        }

    result = (
        client
        .table("prediction_snapshots")
        .insert(payload)
        .execute()
    )

    return {
        "persisted": True,
        "data": result.data
    }


def save_analysis(analysis):
    """
    Convierte el resultado del analizador MLB
    al formato utilizado por prediction_snapshots.
    """

    prediction = analysis.get("prediction", {})
    game = analysis.get("game", {})
    factors = analysis.get("factors", {})

    home_probability = prediction.get(
        "home_probability"
    )

    away_probability = prediction.get(
        "away_probability"
    )

    confidence = prediction.get(
        "confidence"
    )

    available_factors = [
        factors.get("home_team_ops"),
        factors.get("away_team_ops"),
        factors.get("home_team_era"),
        factors.get("away_team_era"),
        factors.get("home_pitcher_era"),
        factors.get("away_pitcher_era")
    ]

    available_count = sum(
        1
        for value in available_factors
        if value is not None
    )

    data_quality = round(
        (
            available_count /
            len(available_factors)
        ) * 100
    )

    payload = {
        "event_id": str(
            game.get("game_id")
        ),
        "sport": "baseball",
        "league": "MLB",
        "model_version": analysis.get(
            "model_version",
            "1.1.0-baseline"
        ),
        "data_cutoff": analysis.get(
            "generated_at"
        ),
        "home_probability": home_probability,
        "away_probability": away_probability,
        "confidence": str(
            confidence
        ),
        "data_quality": data_quality,
        "features": {
            "factors": factors,
            "game": game
        },
        "result_status": "PENDING",
        "prediction_result": None
    }

    return save_prediction(payload)


def settle_prediction(
    event_id,
    actual_winner
):
    """
    Liquida una predicción existente.

    Determina si el ganador proyectado
    coincide con el ganador real.

    Guarda:
    - result_status
    - prediction_result
    - actual_winner
    - settled_at
    """

    client = get_supabase_client()

    if client is None:
        return {
            "updated": False,
            "reason": "Supabase variables not configured"
        }

    existing = (
        client
        .table("prediction_snapshots")
        .select(
            "id,"
            "event_id,"
            "home_probability,"
            "away_probability,"
            "features,"
            "result_status,"
            "prediction_result"
        )
        .eq(
            "event_id",
            str(event_id)
        )
        .eq(
            "result_status",
            "PENDING"
        )
        .execute()
    )

    if not existing.data:
        return {
            "updated": False,
            "reason": (
                "No existe una predicción "
                "PENDING para este event_id"
            ),
            "event_id": str(event_id)
        }

    prediction = existing.data[0]

    features = prediction.get(
        "features"
    ) or {}

    game = features.get(
        "game",
        {}
    )

    home_team = game.get(
        "home"
    )

    away_team = game.get(
        "away"
    )

    home_probability = float(
        prediction.get(
            "home_probability",
            0
        )
    )

    away_probability = float(
        prediction.get(
            "away_probability",
            0
        )
    )

    predicted_winner = None

    if home_probability > away_probability:
        predicted_winner = home_team

    elif away_probability > home_probability:
        predicted_winner = away_team

    if predicted_winner is None:
        return {
            "updated": False,
            "reason": (
                "No se pudo determinar "
                "el ganador proyectado"
            ),
            "event_id": str(event_id)
        }

    correct = (
        predicted_winner == actual_winner
    )

    if correct:
        prediction_result = "CORRECT"
    else:
        prediction_result = "INCORRECT"

    settled_at = datetime.now(
        timezone.utc
    ).isoformat()

    updated = (
        client
        .table("prediction_snapshots")
        .update({
            "result_status": "SETTLED",
            "prediction_result": prediction_result,
            "actual_winner": actual_winner,
            "settled_at": settled_at
        })
        .eq(
            "id",
            prediction["id"]
        )
        .execute()
    )

    return {
        "updated": True,
        "event_id": str(event_id),
        "predicted_winner": predicted_winner,
        "actual_winner": actual_winner,
        "result": prediction_result,
        "settled_at": settled_at,
        "data": updated.data
    }


def get_performance():
    """
    Obtiene estadísticas generales del modelo
    a partir de las predicciones almacenadas.
    """

    client = get_supabase_client()

    if client is None:
        return {
            "success
