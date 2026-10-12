from datetime import datetime, timezone
import math

from repository import get_supabase_client


MODEL_VERSION = "NFL-1.0.0"
SPORT = "football"
LEAGUE = "NFL"


def _effective_result(row):
    features = row.get("features") or {}
    predicted = features.get("predicted_winner")
    actual = row.get("actual_winner")

    if predicted and actual:
        return (
            "CORRECT"
            if str(predicted).strip().upper()
            == str(actual).strip().upper()
            else "INCORRECT"
        )

    return row.get("prediction_result")


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

    # Si ya hay una proyección pendiente, devolvemos la existente.
    # No actualizamos probabilidades, factores ni data_cutoff.
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
    prediction_id = (
        saved_rows[0].get("id")
        if saved_rows
        else None
    )

    return {
        "success": True,
        "saved": True,
        "updated": False,
        "existing": False,
        "prediction_id": prediction_id,
        "data": saved_rows,
    }


def get_nfl_predictions(result_status=None, limit=100):
    """Lista exclusivamente las proyecciones del modelo NFL oficial."""
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
    """Liquida una proyección pendiente sin alterar su snapshot pregame."""
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

    if not predicted_winner or not actual_winner:
        return {
            "success": False,
            "updated": False,
            "event_id": str(event_id),
            "message": "No hay suficientes datos para determinar el resultado.",
        }

    if float(actual_home_score) == float(actual_away_score):
        return {
            "success": False,
            "updated": False,
            "event_id": str(event_id),
            "status": "UNRESOLVED",
            "message": "El marcador está empatado; no se asignó un ganador.",
        }

    prediction_result = (
        "CORRECT"
        if str(predicted_winner).strip().upper()
        == str(actual_winner).strip().upper()
        else "INCORRECT"
    )

    settled_at = datetime.now(timezone.utc).isoformat()

    # Solo actualizamos campos del resultado. El snapshot original
    # (probabilidades, factores, ganador proyectado y data_cutoff)
    # permanece intacto.
    update_data = {
        "result_status": "SETTLED",
        "prediction_result": prediction_result,
        "actual_winner": actual_winner,
        "actual_home_score": int(actual_home_score),
        "actual_away_score": int(actual_away_score),
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
        "actual_winner": actual_winner,
        "actual_home_score": int(actual_home_score),
        "actual_away_score": int(actual_away_score),
        "prediction_result": prediction_result,
        "settled_at": settled_at,
        "data": updated_rows,
    }


def get_nfl_performance():
    """Calcula las métricas observadas del modelo oficial NFL."""
    rows = get_nfl_predictions()

    settled = [
        row for row in rows
        if row.get("result_status") == "SETTLED"
    ]

    correct = sum(
        1 for row in settled
        if _effective_result(row) == "CORRECT"
    )
    incorrect = sum(
        1 for row in settled
        if _effective_result(row) == "INCORRECT"
    )

    confidences = []
    brier_values = []
    log_loss_values = []

    for row in settled:
        try:
            home_probability = float(row.get("home_probability"))
            away_probability = float(row.get("away_probability"))
        except (TypeError, ValueError):
            continue

        features = row.get("features") or {}
        game = features.get("game") or {}
        home_team = game.get("home")
        actual_winner = row.get("actual_winner")

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

    accuracy = correct / len(settled) * 100 if settled else 0.0

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
    """Mide la calibración observada; no modifica el modelo."""
    rows = get_nfl_predictions()
    settled = [
        row for row in rows
        if row.get("result_status") == "SETTLED"
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
            1 for row in bucket
            if _effective_result(row) == "CORRECT"
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
