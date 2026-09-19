import os
from supabase import create_client


def save_prediction(payload):
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")

    if not url or not key:
        return {
            "persisted": False,
            "reason": "Supabase variables not configured"
        }

    result = (
        create_client(url, key)
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
    Convierte el resultado del analizador MLB al formato
    utilizado por prediction_snapshots.
    """

    prediction = analysis.get("prediction", {})
    game = analysis.get("game", {})
    factors = analysis.get("factors", {})

    home_probability = prediction.get("home_probability")
    away_probability = prediction.get("away_probability")
    confidence = prediction.get("confidence")

    # Calidad inicial basada en la cantidad de factores
    available_factors = [
        factors.get("home_team_ops"),
        factors.get("away_team_ops"),
        factors.get("home_team_era"),
        factors.get("away_team_era"),
        factors.get("home_pitcher_era"),
        factors.get("away_pitcher_era")
    ]

    available_count = sum(
        1 for value in available_factors
        if value is not None
    )

    data_quality = round(
        (available_count / len(available_factors)) * 100
    )

    payload = {
        "event_id": str(game.get("game_id")),
        "sport": "baseball",
        "league": "MLB",
        "model_version": analysis.get(
            "model_version",
            "1.1.0-baseline"
        ),
        "data_cutoff": analysis.get("generated_at"),
        "home_probability": home_probability,
        "away_probability": away_probability,
        "confidence": str(confidence),
        "data_quality": data_quality,
        "features": {
            "factors": factors,
            "game": game
        },
        "result_status": "PENDING"
    }

    return save_prediction(payload)
