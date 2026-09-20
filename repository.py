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
        "result_status": "PENDING"
    }

    return save_prediction(payload)


def settle_prediction(
    event_id,
    actual_winner
):
    """
    Actualiza una predicción existente
    con el resultado real del partido.
    """

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")

    if not url or not key:
        return {
            "updated": False,
            "reason": "Supabase variables not configured"
        }

    client = create_client(
        url,
        key
    )

    existing = (
        client
        .table("prediction_snapshots")
        .select(
            "id,event_id,home_probability,"
            "away_probability,features,result_status"
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

    correct = (
        predicted_winner == actual_winner
    )

    result = (
        "CORRECT"
        if correct
        else "INCORRECT"
    )

    updated = (
        client
        .table("prediction_snapshots")
        .update({
            "result_status": "SETTLED",
            "actual_winner": actual_winner,
            "settled_at": (
                __import__(
                    "datetime"
                )
                .datetime
                .now(
                    __import__(
                        "datetime"
                    ).timezone.utc
                )
                .isoformat()
            )
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
        "result": result,
        "data": updated.data
    }
