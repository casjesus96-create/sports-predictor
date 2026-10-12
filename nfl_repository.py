
from datetime import datetime, timezone
import math

from repository import get_supabase_client


MODEL_VERSION = "NFL-1.0.0"
SPORT = "football"
LEAGUE = "NFL"


def _effective_result(row):
    """Devuelve CORRECT, INCORRECT o PUSH sin reinterpretar empates."""
    stored_result = str(row.get("prediction_result") or "").upper()

    if stored_result == "PUSH":
        return "PUSH"

    actual = str(row.get("actual_winner") or "").strip().upper()
    if actual == "TIE":
        return "PUSH"

    features = row.get("features") or {}
    predicted = str(features.get("predicted_winner") or "").strip().upper()

    if predicted and actual:
        return "CORRECT" if predicted == actual else "INCORRECT"

    return stored_result or None


def save_nfl_analysis(analysis):
    """Guarda una proyección oficial sin sobrescribir el snapshot original."""
    if not analysis.get("success"):
        return {
            "success": False,
            "saved": False,
            "message": "No se puede guardar un análisis fallido.",
        }

    game = analysis.get("game") or {}
    prediction = analysis.get("prediction") or {}
    factors = analysis.get("factors") or {}
    event_id = game.get("game_id")

    if not event_id:
        raise ValueError("El análisis NFL no contiene game_id.")

    version = analysis.get("model_version") or MODEL_VERSION
    supabase = get_supabase_client()

    existing = (
        supabase.table("prediction_snapshots")
        .select("*")
        .eq("event_id", str(event_id))
        .eq("sport", SPORT)
        .eq("league", LEAGUE)
        .eq("model_version", version)
        .eq("result_status", "PENDING")
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )

    rows = existing.data or []
    if rows:
        row = rows[0]
        return {
            "success": True,
            "saved": True,
            "updated": False,
            "existing": True,
            "prediction_id": row.get("id"),
            "message": (
                "La proyección original ya existe y se conserva "
                "sin modificaciones."
            ),
            "data": row,
        }

    created_at = (
        analysis.get("generated_at")
        or datetime.now(timezone.utc).isoformat()
    )

    payload = {
        "event_id": str(event_id),
        "sport": SPORT,
        "league": LEAGUE,
        "model_version": version,
        "created_at": created_at,
        "data_cutoff": analysis.get("data_cutoff"),
        "home_probability": prediction.get("home_probability"),
        "away_probability": prediction.get("away_probability"),
        "confidence": prediction.get("confidence"),
        "data_quality": prediction.get("data_quality", 0),
        "features": {
            "game": game,
            "factors": factors,
            "predicted_winner": prediction.get("winner"),
        },
        "result_status": "PENDING",
        "actual_winner": None,
        "actual_home_score": None,
        "actual_away_score": None,
        "settled_at": None,
        "prediction_result": None,
    }

    response = (
        supabase.table("prediction_snapshots")
        .insert(payload)
        .execute()
    )

    saved_rows = response.data or []
    prediction_id = saved_rows[0].get("id") if saved_rows else None

    return {
        "success": True,
        "saved": True,
        "updated": False,
        "existing": False,
        "prediction_id": prediction_id,
        "data": saved_rows,
    }


def get_nfl_predictions(result_status=None, limit=100):
    """Lista exclusivamente las proyecciones del modelo oficial NFL."""
    supabase = get_supabase_client()

    query = (
        supabase.table("prediction_snapshots")
        .select("*")
        .eq("sport", SPORT)
        .eq("league", LEAGUE)
        .eq("model_version", MODEL_VERSION)
        .order("created_at", desc=True)
        .limit(max(1, min(int(limit), 500)))
    )

    if result_status:
        query = query.eq("result_status", result_status.upper())

    response = query.execute()
    return response.data or []


def settle_nfl_prediction(
    event_id,
    actual_winner,
    actual_home_score,
    actual_away_score,
    prediction_id=None,
):
    """Liquida una proyección pendiente; un empate se registra como PUSH."""
    supabase = get_supabase_client()

    query = (
        supabase.table("prediction_snapshots")
        .select("*")
        .eq("event_id", str(event_id))
        .eq("sport", SPORT)
        .eq("league", LEAGUE)
        .eq("model_version", MODEL_VERSION)
        .eq("result_status", "PENDING")
    )

    if prediction_id:
        query = query.eq("id", prediction_id)

    response = (
        query.order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    rows = response.data or []

    if not rows:
        return {
            "success": False,
            "updated": False,
            "event_id": str(event_id),
            "message": (
                "No existe una proyección pendiente para este "
                "partido y el modelo oficial NFL-1.0.0."
            ),
        }

    row = rows[0]
    features = row.get("features") or {}
    game = features.get("game") or {}

    try:
        home_score = float(actual_home_score)
        away_score = float(actual_away_score)
    except (TypeError, ValueError):
        return {
            "success": False,
            "updated": False,
            "event_id": str(event_id),
            "message": "Los marcadores reales no son válidos.",
        }

    if (
        not math.isfinite(home_score)
        or not math.isfinite(away_score)
        or home_score < 0
        or away_score < 0
    ):
        return {
            "success": False,
            "updated": False,
            "event_id": str(event_id),
            "message": "Los marcadores reales no son válidos.",
        }

    is_tie = home_score == away_score

    predicted_winner = features.get("predicted_winner")
    if not predicted_winner:
        try:
            home_probability = float(row.get("home_probability") or 0.5)
            away_probability = float(row.get("away_probability") or 0.5)
        except (TypeError, ValueError):
            home_probability = away_probability = 0.5

        predicted_winner = (
            game.get("home")
            if home_probability >= away_probability
            else game.get("away")
        )

    if is_tie:
        prediction_result = "PUSH"
        actual_winner_to_store = "TIE"
    else:
        if not predicted_winner or not actual_winner:
            return {
                "success": False,
                "updated": False,
                "event_id": str(event_id),
                "message": (
                    "No hay suficientes datos para determinar "
                    "el ganador del partido."
                ),
            }

        prediction_result = (
            "CORRECT"
            if str(predicted_winner).strip().upper()
            == str(actual_winner).strip().upper()
            else "INCORRECT"
        )
        actual_winner_to_store = actual_winner

    settled_at = datetime.now(timezone.utc).isoformat()

    # Solo se modifican los campos del resultado.
    # La predicción pregame y sus factores quedan intactos.
    update_data = {
        "result_status": "SETTLED",
        "prediction_result": prediction_result,
        "actual_winner": actual_winner_to_store,
        "actual_home_score": int(home_score),
        "actual_away_score": int(away_score),
        "settled_at": settled_at,
    }

    updated = (
        supabase.table("prediction_snapshots")
        .update(update_data)
        .eq("id", row["id"])
        .eq("result_status", "PENDING")
        .execute()
    )

    updated_rows = updated.data or []
    if not updated_rows:
        return {
            "success": False,
            "updated": False,
            "event_id": str(event_id),
            "message": (
                "La proyección pudo haber sido liquidada por otra "
                "solicitud. Actualiza la lista para comprobarlo."
            ),
        }

    return {
        "success": True,
        "updated": True,
        "event_id": str(event_id),
        "prediction_id": row["id"],
        "model_version": MODEL_VERSION,
        "predicted_winner": predicted_winner,
        "actual_winner": actual_winner_to_store,
        "actual_home_score": int(home_score),
        "actual_away_score": int(away_score),
        "prediction_result": prediction_result,
        "settled_at": settled_at,
        "data": updated_rows,
    }


def get_nfl_performance():
    """Calcula métricas; los empates no cuentan como aciertos ni fallos."""
    rows = get_nfl_predictions()

    settled = [
        row for row in rows
        if row.get("result_status") == "SETTLED"
    ]

    correct = sum(1 for row in settled if _effective_result(row) == "CORRECT")
    incorrect = sum(
        1 for row in settled if _effective_result(row) == "INCORRECT"
    )
    pushes = sum(1 for row in settled if _effective_result(row) == "PUSH")

    decisive = correct + incorrect
    confidences = []
    brier_values = []
    log_loss_values = []

    for row in settled:
        # Un empate no es un resultado binario para evaluar el ganador.
        if _effective_result(row) == "PUSH":
            continue

        try:
            home_probability = float(row.get("home_probability"))
            away_probability = float(row.get("away_probability"))
        except (TypeError, ValueError):
            continue

        if not (
            math.isfinite(home_probability)
            and math.isfinite(away_probability)
        ):
            continue

        features = row.get("features") or {}
        game = features.get("game") or {}
        home_team = str(game.get("home") or "").strip().upper()
        actual_winner = str(row.get("actual_winner") or "").strip().upper()

        if not home_team or not actual_winner:
            continue

        actual_home = 1.0 if actual_winner == home_team else 0.0
        p = max(0.001, min(0.999, home_probability))

        brier_values.append((p - actual_home) ** 2)
        log_loss_values.append(
            -(
                actual_home * math.log(p)
                + (1.0 - actual_home) * math.log(1.0 - p)
            )
        )
        confidences.append(max(home_probability, away_probability))

    accuracy = correct / decisive * 100 if decisive else 0.0

    return {
        "success": True,
        "sport": "NFL",
        "league": "NFL",
        "model_version": MODEL_VERSION,
        "summary": {
            "total_predictions": len(rows),
            "pending_predictions": sum(
                1 for row in rows
                if row.get("result_status") == "PENDING"
            ),
            "settled_predictions": len(settled),
            "correct_predictions": correct,
            "incorrect_predictions": incorrect,
            "push_predictions": pushes,
            "decisive_predictions": decisive,
            "accuracy_percentage": round(accuracy, 2),
            "average_confidence": round(
                sum(confidences) / len(confidences)
                if confidences else 0.0,
                4,
            ),
            "brier_score": round(
                sum(brier_values) / len(brier_values)
                if brier_values else 0.0,
                6,
            ),
            "log_loss": round(
                sum(log_loss_values) / len(log_loss_values)
                if log_loss_values else 0.0,
                6,
            ),
        },
    }


def get_nfl_calibration(minimum_sample=30):
    """Mide la calibración solo con partidos que tuvieron ganador."""
    rows = get_nfl_predictions()
    settled = [
        row for row in rows
        if row.get("result_status") == "SETTLED"
        and _effective_result(row) in {"CORRECT", "INCORRECT"}
    ]

    bins = [
        (0.50, 0.55),
        (0.55, 0.60),
        (0.60, 0.65),
        (0.65, 0.70),
        (0.70, 0.75),
        (0.75, 0.80),
        (0.80, 0.85),
        (0.85, 0.90),
        (0.90, 0.951),
    ]

    calibration = []

    for low, high in bins:
        bucket = []

        for row in settled:
            try:
                confidence = max(
                    float(row.get("home_probability")),
                    float(row.get("away_probability")),
                )
            except (TypeError, ValueError):
                continue

            if low <= confidence < high:
                bucket.append(row)

        if not bucket:
            continue

        count = len(bucket)
        wins = sum(
            1 for row in bucket if _effective_result(row) == "CORRECT"
        )
        observed_accuracy = wins / count

        average_confidence = sum(
            max(
                float(row.get("home_probability") or 0.5),
                float(row.get("away_probability") or 0.5),
            )
            for row in bucket
        ) / count

        calibration.append({
            "range": f"{low:.0%}-{min(high, 0.95):.0%}",
            "min": low,
            "max": min(high, 0.95),
            "count": count,
            "average_confidence": round(average_confidence, 4),
            "observed_accuracy": round(observed_accuracy, 4),
            "calibration_error": round(
                observed_accuracy - average_confidence,
                4,
            ),
        })

    sample_size = len(settled)
    ready = sample_size >= int(minimum_sample)

    return {
        "success": True,
        "sport": "NFL",
        "league": "NFL",
        "model_version": MODEL_VERSION,
        "sample_size": sample_size,
        "minimum_sample_required": int(minimum_sample),
        "calibration_ready": ready,
        "method": "confidence_bucket_reliability",
        "calibration": calibration,
        "message": (
            "Existe una muestra suficiente para estudiar una "
            "recalibración estadística."
            if ready
            else "La muestra todavía no es suficiente para "
                 "recalibrar el modelo de forma responsable."
        ),
    }


def get_nfl_pending_predictions():
    return get_nfl_predictions(result_status="PENDING")
