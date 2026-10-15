
from datetime import datetime, timezone
import os

from probability_metrics import calculate_probability_metrics

from supabase import create_client, Client


# =========================================================
# CONFIGURACIÓN DEL MODELO
# =========================================================

CURRENT_MODEL_VERSION = "2.0.0-matchup"


# =========================================================
# SUPABASE
# =========================================================

def get_supabase_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY"
        )

    return create_client(url, key)


# =========================================================
# GUARDAR PREDICCIÓN DIRECTA
# =========================================================

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
    """
    Guarda una predicción en prediction_snapshots.
    Se mantiene para compatibilidad con el endpoint experimental.
    """
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


# =========================================================
# GUARDAR ANÁLISIS COMPLETO
# =========================================================

def _matchup_snapshot_metrics(features):
    """Compact, comparable summary of confirmed MLB lineup/BvP coverage."""
    factors = (features or {}).get("factors") or {}
    matchup = factors.get("batter_pitcher_matchups") or {}
    sides = []
    confirmed_count = 0
    confirmed_hitters = 0
    available_bvp_hitters = 0
    signatures = {}

    for side in ("home_team", "away_team"):
        team = matchup.get(side) or {}
        hitters = team.get("hitters") or []
        confirmed = bool(team.get("lineup_confirmed"))
        if confirmed:
            confirmed_count += 1
            confirmed_hitters += len(hitters)
        available_bvp_hitters += sum(
            1 for hitter in hitters
            if ((hitter.get("vs_pitcher") or {}).get("available"))
        )
        signatures[side] = [
            str(hitter.get("player_id") or hitter.get("player_name") or "")
            for hitter in hitters
        ] if confirmed else []
        sides.append({
            "side": side,
            "lineup_confirmed": confirmed,
            "lineup_status": team.get("lineup_status"),
            "lineup_source": team.get("lineup_source"),
            "hitter_count": len(hitters),
            "available_bvp_hitters": sum(
                1 for hitter in hitters
                if ((hitter.get("vs_pitcher") or {}).get("available"))
            ),
        })

    pitchers = factors.get("probable_pitchers") or {}
    pitcher_ids = {}
    for side in ("home", "away"):
        pitcher = pitchers.get(side) or {}
        pitcher_ids[side] = (
            pitcher.get("pitcher_id")
            or pitcher.get("id")
        )

    return {
        "confirmed_lineup_count": confirmed_count,
        "confirmed_hitter_count": confirmed_hitters,
        "available_bvp_hitter_count": available_bvp_hitters,
        "lineup_signatures": signatures,
        "lineups": sides,
        "pitcher_ids": pitcher_ids,
    }


def _pending_refresh_reason(existing, payload):
    """Return a reason only when fresh pregame information materially improves."""
    old_features = existing.get("features") or {}
    new_features = payload.get("features") or {}
    old_metrics = _matchup_snapshot_metrics(old_features)
    new_metrics = _matchup_snapshot_metrics(new_features)

    if new_metrics["confirmed_lineup_count"] > old_metrics["confirmed_lineup_count"]:
        return "Se publicaron alineaciones confirmadas de MLB."

    if (
        new_metrics["lineup_signatures"] != old_metrics["lineup_signatures"]
        and new_metrics["confirmed_lineup_count"] > 0
    ):
        return "Cambió una alineación confirmada de MLB."

    if new_metrics["available_bvp_hitter_count"] > old_metrics["available_bvp_hitter_count"]:
        return "Hay más historial directo bateador-contra-pitcher disponible."

    old_pitchers = old_metrics["pitcher_ids"]
    new_pitchers = new_metrics["pitcher_ids"]
    if any(
        new_pitchers.get(side) and new_pitchers.get(side) != old_pitchers.get(side)
        for side in ("home", "away")
    ):
        return "Se actualizó la identificación del pitcher probable."

    # A missing legacy quality score is unknown, not zero; do not treat it
    # as evidence of improvement merely because the new score is populated.
    try:
        old_quality_raw = existing.get("data_quality")
        new_quality_raw = payload.get("data_quality")
        if old_quality_raw is not None and new_quality_raw is not None:
            old_quality = float(old_quality_raw)
            new_quality = float(new_quality_raw)
            if new_quality >= old_quality + 3:
                return "Mejoró de forma material la cobertura de datos."
    except (TypeError, ValueError):
        pass

    # The official model's probabilities are not changed just because an
    # unrelated re-run differs. Refresh only when pregame evidence materially
    # improves (lineups, batter-vs-pitcher history, probable pitcher, coverage).

    return None


def save_analysis(analysis):
    """
    Guarda la predicción oficial MLB 2.0.0-matchup.

    Un snapshot PENDING se refresca únicamente cuando el nuevo análisis pregame
    aporta mejoras materiales. La misma fila conserva un historial acotado de
    revisiones; nunca se modifica un resultado liquidado ni se duplica el evento.
    """
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
        raise ValueError("El análisis no contiene game_id.")

    game_status = str(game.get("status") or "").strip().lower()
    if game_status in {"live", "final", "in progress", "game over"}:
        return {
            "success": False,
            "saved": False,
            "message": (
                "No se puede crear ni refrescar una predicción cuando el partido "
                "ya comenzó o terminó."
            ),
            "event_id": str(event_id),
            "status": game.get("status"),
        }

    supabase = get_supabase_client()
    model_version = analysis.get("model_version", CURRENT_MODEL_VERSION)
    generated_at = analysis.get("generated_at") or datetime.now(timezone.utc).isoformat()

    data_quality = prediction.get("data_quality")
    if data_quality is None:
        data_quality = 0

    features = {
        "game": game,
        "factors": factors,
        "predicted_winner": prediction.get("winner"),
        "experimental_probability": prediction.get("experimental_probability"),
    }

    payload = {
        "event_id": str(event_id),
        "sport": "baseball",
        "league": "MLB",
        "model_version": model_version,
        "created_at": generated_at,
        "data_cutoff": generated_at,
        "home_probability": prediction.get("home_probability"),
        "away_probability": prediction.get("away_probability"),
        "confidence": prediction.get("confidence"),
        "data_quality": data_quality,
        "features": features,
        "result_status": "PENDING",
        "actual_winner": None,
        "actual_home_score": None,
        "actual_away_score": None,
        "settled_at": None,
        "prediction_result": None,
    }

    existing_response = (
        supabase.table("prediction_snapshots")
        .select("*")
        .eq("event_id", str(event_id))
        .eq("model_version", model_version)
        .eq("result_status", "PENDING")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    existing_rows = existing_response.data or []

    if existing_rows:
        existing = existing_rows[0]
        refresh_reason = _pending_refresh_reason(existing, payload)
        if not refresh_reason:
            return {
                "success": True,
                "saved": True,
                "updated_existing": False,
                "existing_prediction_preserved": True,
                "message": (
                    "Se consultaron de nuevo los datos pregame, pero no se detectó "
                    "una mejora material. Se conservó la predicción pendiente."
                ),
                "refresh_reason": None,
                "data": existing_rows,
            }

        old_features = existing.get("features") or {}
        old_metrics = _matchup_snapshot_metrics(old_features)
        old_revision = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "data_cutoff": existing.get("data_cutoff"),
            "reason": refresh_reason,
            "predicted_winner": old_features.get("predicted_winner"),
            "home_probability": existing.get("home_probability"),
            "away_probability": existing.get("away_probability"),
            "confidence": existing.get("confidence"),
            "data_quality": existing.get("data_quality"),
            "experimental_probability": old_features.get("experimental_probability"),
            "lineup_metrics": old_metrics,
            "previous_batter_pitcher_matchups": (
                ((old_features.get("factors") or {}).get("batter_pitcher_matchups"))
            ),
        }
        revisions = list(old_features.get("analysis_revisions") or [])
        revisions.append(old_revision)
        # Bound JSON growth while keeping recent revision audit data.
        features["analysis_revisions"] = revisions[-10:]
        features["last_revision_reason"] = refresh_reason

        update_payload = {
            "data_cutoff": generated_at,
            "home_probability": payload["home_probability"],
            "away_probability": payload["away_probability"],
            "confidence": payload["confidence"],
            "data_quality": payload["data_quality"],
            "features": features,
        }
        updated_response = (
            supabase.table("prediction_snapshots")
            .update(update_payload)
            .eq("id", existing.get("id"))
            .eq("result_status", "PENDING")
            .execute()
        )
        updated_rows = updated_response.data or []
        if not updated_rows:
            return {
                "success": True,
                "saved": True,
                "updated_existing": False,
                "existing_prediction_preserved": True,
                "message": (
                    "El snapshot dejó de estar PENDING durante el reanálisis; "
                    "no se modificó un resultado liquidado."
                ),
                "refresh_reason": refresh_reason,
                "data": [existing],
            }

        return {
            "success": True,
            "saved": True,
            "updated_existing": True,
            "existing_prediction_preserved": False,
            "message": "Se refrescó el snapshot pendiente y se guardó la revisión anterior.",
            "refresh_reason": refresh_reason,
            "data": updated_rows,
        }

    response = (
        supabase.table("prediction_snapshots")
        .insert(payload)
        .execute()
    )
    return {
        "success": True,
        "saved": True,
        "updated_existing": False,
        "existing_prediction_preserved": False,
        "message": "Predicción guardada como un nuevo snapshot.",
        "refresh_reason": None,
        "data": response.data,
    }


# =========================================================
# PREDICCIONES PENDIENTES
# =========================================================

def get_pending_predictions():
    """Obtiene las predicciones que todavía no han sido liquidadas."""
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


# =========================================================
# LIQUIDAR PREDICCIÓN
# =========================================================

def settle_prediction(
    event_id,
    actual_winner,
    actual_home_score,
    actual_away_score,
    prediction_id=None,
    model_version=CURRENT_MODEL_VERSION,
):
    """
    Liquida una predicción pendiente y registra CORRECT o INCORRECT.
    """
    supabase = get_supabase_client()

    query = (
        supabase
        .table("prediction_snapshots")
        .select("*")
        .eq("event_id", str(event_id))
        .eq("result_status", "PENDING")
    )

    if prediction_id:
        query = query.eq("id", prediction_id)
    elif model_version:
        query = query.eq("model_version", model_version)

    existing = (
        query
        .order("created_at", desc=True)
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
    features = prediction.get("features") or {}

    predicted_winner = features.get("predicted_winner")

    # Never derive the prediction from the actual result: that would
    # leak the outcome into the forecast and can create false CORRECT rows.
    if not predicted_winner:
        game = features.get("game") or {}
        home_name = game.get("home")
        away_name = game.get("away")
        try:
            home_probability = float(prediction.get("home_probability"))
            away_probability = float(prediction.get("away_probability"))
        except (TypeError, ValueError):
            home_probability = None
            away_probability = None

        if (
            home_name
            and away_name
            and home_name != away_name
            and home_probability is not None
            and away_probability is not None
            and home_probability >= 0
            and away_probability >= 0
            and abs((home_probability + away_probability) - 1.0) <= 0.02
            and home_probability != away_probability
        ):
            predicted_winner = (
                home_name if home_probability > away_probability else away_name
            )

    if not predicted_winner:
        return {
            "updated": False,
            "reason": (
                "La predicción original no contiene ganador ni probabilidades "
                "válidas suficientes. El registro permanece PENDING para revisión."
            ),
            "event_id": str(event_id),
        }

    if predicted_winner not in {
        ((features.get("game") or {}).get("home")),
        ((features.get("game") or {}).get("away")),
    }:
        return {
            "updated": False,
            "reason": (
                "El ganador pronosticado no coincide con los equipos guardados. "
                "El registro permanece PENDING para revisión."
            ),
            "event_id": str(event_id),
        }

    if actual_winner not in {
        ((features.get("game") or {}).get("home")),
        ((features.get("game") or {}).get("away")),
    }:
        return {
            "updated": False,
            "reason": (
                "El ganador real no coincide con los equipos guardados. "
                "El registro permanece PENDING para revisión."
            ),
            "event_id": str(event_id),
        }

    prediction_result = (
        "CORRECT" if predicted_winner == actual_winner else "INCORRECT"
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
        "predicted_winner": predicted_winner,
        "actual_winner": actual_winner,
        "actual_home_score": actual_home_score,
        "actual_away_score": actual_away_score,
        "settled_at": now,
        "data": response.data,
    }


# =========================================================
# RESULTADO EFECTIVO
# =========================================================

def _effective_prediction_result(row):
    """
    Recalcula el resultado de una predicción liquidada a partir
    del ganador proyectado y el ganador real.
    """
    stored = row.get("prediction_result")

    if row.get("result_status") != "SETTLED":
        return stored

    features = row.get("features") or {}
    predicted = features.get("predicted_winner")
    actual = row.get("actual_winner")

    if predicted and actual:
        return (
            "CORRECT"
            if str(predicted).strip() == str(actual).strip()
            else "INCORRECT"
        )

    return stored


def reconcile_settled_prediction(event_id):
    """
    Corrige registros SETTLED cuyo resultado almacenado no coincide
    con el ganador proyectado y el ganador real.
    """
    supabase = get_supabase_client()

    response = (
        supabase
        .table("prediction_snapshots")
        .select("*")
        .eq("event_id", str(event_id))
        .eq("result_status", "SETTLED")
        .execute()
    )

    rows = response.data or []
    updates = []

    for row in rows:
        effective = _effective_prediction_result(row)

        if effective and effective != row.get("prediction_result"):
            updated = (
                supabase
                .table("prediction_snapshots")
                .update({"prediction_result": effective})
                .eq("id", row.get("id"))
                .execute()
            )

            updates.append({
                "id": row.get("id"),
                "old": row.get("prediction_result"),
                "new": effective,
                "data": updated.data,
            })

    return {
        "success": True,
        "event_id": str(event_id),
        "checked": len(rows),
        "updated": len(updates),
        "updates": updates,
    }


# =========================================================
# ESTADÍSTICAS DE RENDIMIENTO
# =========================================================

def get_performance():
    """
    Calcula el rendimiento general y por versión.
    Las predicciones CANCELLED se contabilizan aparte
    y no cuentan como aciertos ni errores.
    """
    supabase = get_supabase_client()

    response = (
        supabase
        .table("prediction_snapshots")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    rows = response.data or []

    versions = sorted({
        row.get("model_version") or "unknown"
        for row in rows
    })

    def calculate_stats(model_rows):
        total = len(model_rows)

        pending = sum(
            1 for row in model_rows
            if str(row.get("result_status") or "").upper() == "PENDING"
        )

        settled = sum(
            1 for row in model_rows
            if str(row.get("result_status") or "").upper() == "SETTLED"
        )

        cancelled = sum(
            1 for row in model_rows
            if str(row.get("result_status") or "").upper() == "CANCELLED"
        )

        correct = sum(
            1 for row in model_rows
            if _effective_prediction_result(row) == "CORRECT"
        )

        incorrect = sum(
            1 for row in model_rows
            if _effective_prediction_result(row) == "INCORRECT"
        )

        confidences = []
        for row in model_rows:
            try:
                value = row.get("confidence")
                if value is not None:
                    confidences.append(float(value))
            except (TypeError, ValueError):
                pass

        data_qualities = []
        for row in model_rows:
            try:
                value = row.get("data_quality")
                if value is not None:
                    data_qualities.append(float(value))
            except (TypeError, ValueError):
                pass

        accuracy = (
            (correct / settled) * 100
            if settled > 0 else 0
        )

        average_confidence = (
            sum(confidences) / len(confidences)
            if confidences else 0
        )

        average_data_quality = (
            sum(data_qualities) / len(data_qualities)
            if data_qualities else 0
        )

        probability_metrics = calculate_probability_metrics(model_rows)

        return {
            "total_predictions": total,
            "pending_predictions": pending,
            "settled_predictions": settled,
            "cancelled_predictions": cancelled,
            "correct_predictions": correct,
            "incorrect_predictions": incorrect,
            "accuracy_percentage": round(accuracy, 2),
            "average_confidence": round(average_confidence, 4),
            "average_data_quality": round(average_data_quality, 2),
            "probability_metrics": probability_metrics,
        }

    overall = calculate_stats(rows)

    models = {}
    for version in versions:
        model_rows = [
            row for row in rows
            if (row.get("model_version") or "unknown") == version
        ]
        models[version] = calculate_stats(model_rows)

    return {
        "success": True,
        "model": {
            "versions": versions,
            "current": CURRENT_MODEL_VERSION,
        },
        "summary": overall,
        "models": models,
        "results": {
            "correct": overall["correct_predictions"],
            "incorrect": overall["incorrect_predictions"],
            "pending": overall["pending_predictions"],
            "cancelled": overall["cancelled_predictions"],
        },
    }


# =========================================================
# LISTAR PREDICCIONES
# =========================================================

def get_predictions():
    """
    Devuelve las predicciones almacenadas
    en un formato limpio para la API/interfaz.
    """
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
                    if float(home_probability) >= float(away_probability):
                        prediction = home_name
                    else:
                        prediction = away_name
                except (TypeError, ValueError):
                    prediction = None

        predictions.append({
            "id": row.get("id"),
            "event_id": row.get("event_id"),
            "model_version": row.get("model_version"),
            "created_at": row.get("created_at"),
            "data_cutoff": row.get("data_cutoff"),
            "game": {
                "date": game.get("date"),
                "status": game.get("status"),
                "detailed_status": game.get("detailed_status"),
                "venue": game.get("venue"),
                "home": game.get("home"),
                "away": game.get("away"),
                "home_team_id": game.get("home_team_id"),
                "away_team_id": game.get("away_team_id"),
            },
            "prediction": {
                "predicted_winner": prediction,
                "home_probability": home_probability,
                "away_probability": away_probability,
                "confidence": row.get("confidence"),
                "data_quality": row.get("data_quality"),
                "experimental_probability": features.get("experimental_probability"),
            },
            "result": {
                "status": row.get("result_status"),
                "prediction_result": _effective_prediction_result(row),
                "stored_prediction_result": row.get("prediction_result"),
                "actual_winner": row.get("actual_winner"),
                "actual_home_score": row.get("actual_home_score"),
                "actual_away_score": row.get("actual_away_score"),
                "settled_at": row.get("settled_at"),
            },
            "factors": features.get("factors", {}),
        })

    return {
        "success": True,
        "total": len(predictions),
        "predictions": predictions,
    }
