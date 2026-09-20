from datetime import datetime, timezone

from supabase import create_client, Client
import os


def get_supabase_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY"
        )

    return create_client(url, key)


def save_prediction(
    event_id,
    sport,
    league,
    model_version,
    home_probability,
    away_probability,
    confidence,
    data_quality,
    features=None,
):
    supabase = get_supabase_client()

    payload = {
        "event_id": str(event_id),
        "sport": sport,
        "league": league,
        "model_version": model_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_cutoff": datetime.now(timezone.utc).isoformat(),
        "home_probability": home_probability,
        "away_probability": away_probability,
        "confidence": confidence,
        "data_quality": data_quality,
        "features": features or {},
        "result_status": "PENDING",
        "actual_winner": None,
        "actual_home_score": None,
        "actual_away_score": None,
        "settled_at": None,
        "prediction_result": None,
    }

    response = (
        supabase
        .table("prediction_snapshots")
        .insert(payload)
        .execute()
    )

    return response.data


def save_analysis(analysis):
    if not analysis.get("success"):
        return {
            "success": False,
            "message": "No se puede guardar un análisis fallido."
        }

    game = analysis["game"]
    prediction = analysis["prediction"]
    factors = analysis.get("factors", {})

    supabase = get_supabase_client()

    payload = {
        "event_id": str(game["game_id"]),
        "sport": "baseball",
        "league": "MLB",
        "model_version": analysis.get(
            "model_version",
            "1.1.0-baseline"
        ),
        "created_at": analysis.get(
            "generated_at",
            datetime.now(timezone.utc).isoformat()
        ),
        "data_cutoff": datetime.now(timezone.utc).isoformat(),
        "home_probability": prediction["home_probability"],
        "away_probability": prediction["away_probability"],
        "confidence": prediction["confidence"],
        "data_quality": 100,
        "features": {
            "game": game,
            "factors": factors,
            "predicted_winner": prediction["winner"],
        },
        "result_status": "PENDING",
        "actual_winner": None,
        "actual_home_score": None,
        "actual_away_score": None,
        "settled_at": None,
        "prediction_result": None,
    }

    response = (
        supabase
        .table("prediction_snapshots")
        .insert(payload)
        .execute()
    )

    return {
        "success": True,
        "saved": True,
        "data": response.data,
    }


def get_pending_predictions():
    """
    Obtiene todas las predicciones que todavía
    no han sido liquidadas.
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table("prediction_snapshots")
        .select(
            "id,event_id,model_version,"
            "result_status,created_at"
        )
        .eq("result_status", "PENDING")
        .order("created_at", desc=False)
        .execute()
    )

    return response.data or []


def settle_prediction(
    event_id,
    actual_winner,
    actual_home_score,
    actual_away_score,
):
    supabase = get_supabase_client()

    existing = (
        supabase
        .table("prediction_snapshots")
        .select("*")
        .eq("event_id", str(event_id))
        .eq("result_status", "PENDING")
        .limit(1)
        .execute()
    )

    if not existing.data:
        return {
            "updated": False,
            "reason": (
                "No existe una predicción PENDING "
                "para este event_id"
            ),
            "event_id": str(event_id),
        }

    prediction = existing.data[0]

    home_probability = float(
        prediction.get("home_probability") or 0
    )

    away_probability = float(
        prediction.get("away_probability") or 0
    )

    predicted_winner = (
        prediction.get("features", {})
        .get("predicted_winner")
    )

    if not predicted_winner:
        home_name = (
            prediction.get("features", {})
            .get("game", {})
            .get("home")
        )

        away_name = (
            prediction.get("features", {})
            .get("game", {})
            .get("away")
        )

        if actual_winner == home_name:
            predicted_winner = home_name

        elif actual_winner == away_name:
            predicted_winner = away_name

        else:
            predicted_winner = (
                home_name
                if home_probability >= away_probability
                else away_name
            )

    prediction_result = (
        "CORRECT"
        if predicted_winner == actual_winner
        else "INCORRECT"
    )

    now = datetime.now(timezone.utc).isoformat()

    update_data = {
        "result_status": "SETTLED",
        "prediction_result": prediction_result,
        "actual_winner": actual_winner,
        "actual_home_score": actual_home_score,
        "actual_away_score": actual_away_score,
        "settled_at": now,
    }

    response = (
        supabase
        .table("prediction_snapshots")
        .update(update_data)
        .eq("id", prediction["id"])
        .execute()
    )

    return {
        "updated": True,
        "event_id": str(event_id),
        "prediction_result": prediction_result,
        "actual_winner": actual_winner,
        "actual_home_score": actual_home_score,
        "actual_away_score": actual_away_score,
        "settled_at": now,
        "data": response.data,
    }


def get_performance():
    supabase = get_supabase_client()

    response = (
        supabase
        .table("prediction_snapshots")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    rows = response.data or []

    versions = sorted(
        list(
            {
                row.get("model_version") or "unknown"
                for row in rows
            }
        )
    )

    def calculate_stats(model_rows):
        total = len(model_rows)

        pending = sum(
            1
            for row in model_rows
            if row.get("result_status") == "PENDING"
        )

        settled = sum(
            1
            for row in model_rows
            if row.get("result_status") == "SETTLED"
        )

        correct = sum(
            1
            for row in model_rows
            if row.get("prediction_result") == "CORRECT"
        )

        incorrect = sum(
            1
            for row in model_rows
            if row.get("prediction_result") == "INCORRECT"
        )

        confidences = []

        for row in model_rows:
            value = row.get("confidence")

            try:
                confidences.append(float(value))
            except (TypeError, ValueError):
                pass

        data_qualities = []

        for row in model_rows:
            value = row.get("data_quality")

            try:
                data_qualities.append(float(value))
            except (TypeError, ValueError):
                pass

        accuracy = (
            (correct / settled) * 100
            if settled > 0
            else 0
        )

        average_confidence = (
            sum(confidences) / len(confidences)
            if confidences
            else 0
        )

        average_data_quality = (
            sum(data_qualities) / len(data_qualities)
            if data_qualities
            else 0
        )

        return {
            "total_predictions": total,
            "pending_predictions": pending,
            "settled_predictions": settled,
            "correct_predictions": correct,
            "incorrect_predictions": incorrect,
            "accuracy_percentage": round(
                accuracy,
                2
            ),
            "average_confidence": round(
                average_confidence,
                4
            ),
            "average_data_quality": round(
                average_data_quality,
                2
            ),
        }

    overall = calculate_stats(rows)

    models = {}

    for version in versions:
        model_rows = [
            row
            for row in rows
            if (row.get("model_version") or "unknown") == version
        ]

        models[version] = calculate_stats(model_rows)

    return {
        "success": True,
        "model": {
            "versions": versions,
            "current": "1.1.0-baseline",
        },
        "summary": overall,
        "models": models,
        "results": {
            "correct": overall["correct_predictions"],
            "incorrect": overall["incorrect_predictions"],
            "pending": overall["pending_predictions"],
        },
    }


def get_predictions():
    supabase = get_supabase_client()

    response = (
        supabase
        .table("prediction_snapshots")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    rows = response.data or []

    predictions = []

    for row in rows:
        features = row.get("features") or {}
        game = features.get("game") or {}
        prediction = features.get("predicted_winner")

        home_probability = row.get("home_probability")
        away_probability = row.get("away_probability")

        if prediction is None:
            home_name = game.get("home")
            away_name = game.get("away")

            if home_name and away_name:
                try:
                    if float(home_probability) >= float(
                        away_probability
                    ):
                        prediction = home_name
                    else:
                        prediction = away_name
                except (TypeError, ValueError):
                    prediction = None

        predictions.append(
            {
                "id": row.get("id"),
                "event_id": row.get("event_id"),
                "model_version": row.get("model_version"),
                "created_at": row.get("created_at"),
                "data_cutoff": row.get("data_cutoff"),

                "game": {
                    "date": game.get("date"),
                    "status": game.get("status"),
                    "venue": game.get("venue"),
                    "home": game.get("home"),
                    "away": game.get("away"),
                },

                "prediction": {
                    "predicted_winner": prediction,
                    "home_probability": home_probability,
                    "away_probability": away_probability,
                    "confidence": row.get("confidence"),
                    "data_quality": row.get("data_quality"),
                },

                "result": {
                    "status": row.get("result_status"),
                    "prediction_result": row.get(
                        "prediction_result"
                    ),
                    "actual_winner": row.get(
                        "actual_winner"
                    ),
                    "actual_home_score": row.get(
                        "actual_home_score"
                    ),
                    "actual_away_score": row.get(
                        "actual_away_score"
                    ),
                    "settled_at": row.get(
                        "settled_at"
                    ),
                },

                "factors": features.get(
                    "factors",
                    {}
                ),
            }
        )

    return {
        "success": True,
        "total": len(predictions),
        "predictions": predictions,
    }
