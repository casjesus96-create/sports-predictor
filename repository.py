from datetime import datetime, timezone
import os
import unicodedata
import re

from supabase import create_client, Client


# =========================================================
# CONFIGURACIÓN DEL MODELO
# =========================================================

CURRENT_MODEL_VERSION = "1.2.0-form"


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

    return create_client(
        url,
        key
    )


# =========================================================
# UTILIDADES
# =========================================================

def normalize_team_name(value):
    """
    Normaliza nombres de equipos para poder compararlos
    de forma segura.

    Ejemplos:

    Chicago Cubs
    chicago cubs
    Chicago  Cubs

    Todos terminan representando el mismo nombre normalizado.
    """

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    # Eliminar acentos
    text = unicodedata.normalize(
        "NFKD",
        text
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    # Minúsculas
    text = text.lower()

    # Normalizar espacios
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    # Eliminar espacios extremos
    text = text.strip()

    return text


def teams_match(team_a, team_b):
    """
    Determina si dos nombres representan al mismo equipo.
    """

    normalized_a = normalize_team_name(
        team_a
    )

    normalized_b = normalize_team_name(
        team_b
    )

    if not normalized_a or not normalized_b:
        return False

    return normalized_a == normalized_b


def safe_float(value, default=None):
    """
    Convierte un valor a float de forma segura.
    """

    try:

        if value is None:
            return default

        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return default


def determine_predicted_winner(
    prediction,
    features,
    actual_winner=None,
):
    """
    Determina de forma robusta el ganador proyectado.

    Prioridad:

    1. predicted_winner guardado.
    2. Ganador reconstruido por probabilidades.
    3. None.

    Si el valor guardado no coincide con ninguno de los
    equipos conocidos pero las probabilidades permiten
    reconstruir el ganador, se utiliza la probabilidad.
    """

    prediction = prediction or {}
    features = features or {}

    # -----------------------------------------------------
    # Ganador guardado directamente
    # -----------------------------------------------------

    stored_winner = features.get(
        "predicted_winner"
    )

    game = (
        features.get("game")
        or {}
    )

    home_name = game.get(
        "home"
    )

    away_name = game.get(
        "away"
    )

    # -----------------------------------------------------
    # Si el ganador guardado corresponde a alguno de los
    # equipos, conservarlo.
    # -----------------------------------------------------

    if stored_winner:

        if (
            teams_match(
                stored_winner,
                home_name
            )
            and home_name
        ):
            return home_name

        if (
            teams_match(
                stored_winner,
                away_name
            )
            and away_name
        ):
            return away_name

    # -----------------------------------------------------
    # Reconstruir utilizando probabilidades
    # -----------------------------------------------------

    home_probability = safe_float(
        prediction.get(
            "home_probability"
        )
    )

    away_probability = safe_float(
        prediction.get(
            "away_probability"
        )
    )

    if (
        home_name
        and away_name
        and home_probability is not None
        and away_probability is not None
    ):

        if home_probability >= away_probability:
            return home_name

        return away_name

    # -----------------------------------------------------
    # Último recurso:
    # conservar el valor almacenado.
    # -----------------------------------------------------

    if stored_winner:
        return stored_winner

    return None


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

    Esta función se mantiene para compatibilidad con
    el endpoint experimental.
    """

    supabase = get_supabase_client()

    payload = {
        "event_id": str(event_id),

        "sport": sport,

        "league": league,

        "model_version": model_version,

        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "data_cutoff": datetime.now(
            timezone.utc
        ).isoformat(),

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
        .table(
            "prediction_snapshots"
        )
        .insert(
            payload
        )
        .execute()
    )

    return response.data


# =========================================================
# GUARDAR ANÁLISIS COMPLETO
# =========================================================

def save_analysis(analysis):
    """
    Guarda un análisis generado por analyzer.py.

    Conserva:

    - probabilidades
    - ganador proyectado
    - confianza
    - calidad real de datos
    - factores
    - información del partido
    - versión del modelo
    """

    if not analysis.get(
        "success"
    ):

        return {
            "success": False,
            "saved": False,
            "message": (
                "No se puede guardar un análisis fallido."
            ),
        }

    game = (
        analysis.get("game")
        or {}
    )

    prediction = (
        analysis.get("prediction")
        or {}
    )

    factors = (
        analysis.get("factors")
        or {}
    )

    event_id = game.get(
        "game_id"
    )

    if not event_id:

        raise ValueError(
            "El análisis no contiene game_id."
        )

    supabase = get_supabase_client()

    model_version = analysis.get(
        "model_version",
        CURRENT_MODEL_VERSION
    )

    generated_at = analysis.get(
        "generated_at"
    )

    if not generated_at:

        generated_at = datetime.now(
            timezone.utc
        ).isoformat()

    # -----------------------------------------------------
    # Calidad REAL calculada por analyzer.py
    # -----------------------------------------------------

    data_quality = prediction.get(
        "data_quality"
    )

    if data_quality is None:
        data_quality = 0

    # -----------------------------------------------------
    # Información completa
    # -----------------------------------------------------

    features = {
        "game": game,

        "factors": factors,

        "predicted_winner": prediction.get(
            "winner"
        ),
    }

    payload = {
        "event_id": str(
            event_id
        ),

        "sport": "baseball",

        "league": "MLB",

        "model_version": model_version,

        "created_at": generated_at,

        "data_cutoff": generated_at,

        "home_probability": prediction.get(
            "home_probability"
        ),

        "away_probability": prediction.get(
            "away_probability"
        ),

        "confidence": prediction.get(
            "confidence"
        ),

        "data_quality": data_quality,

        "features": features,

        "result_status": "PENDING",

        "actual_winner": None,

        "actual_home_score": None,

        "actual_away_score": None,

        "settled_at": None,

        "prediction_result": None,
    }

    response = (
        supabase
        .table(
            "prediction_snapshots"
        )
        .insert(
            payload
        )
        .execute()
    )

    return {
        "success": True,
        "saved": True,
        "data": response.data,
    }


# =========================================================
# PREDICCIONES PENDIENTES
# =========================================================

def get_pending_predictions():
    """
    Obtiene todas las predicciones que todavía
    no han sido liquidadas.
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "prediction_snapshots"
        )
        .select(
            "id,event_id,model_version,"
            "result_status,created_at"
        )
        .eq(
            "result_status",
            "PENDING"
        )
        .order(
            "created_at",
            desc=False
        )
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
):
    """
    Liquida la predicción PENDING correspondiente
    al partido.

    Resultado:

    - CORRECT
    - INCORRECT

    La comparación del ganador se realiza mediante
    nombres normalizados para evitar errores por:

    - mayúsculas/minúsculas
    - espacios
    - acentos
    - diferencias de formato
    """

    supabase = get_supabase_client()

    event_id = str(
        event_id
    )

    # -----------------------------------------------------
    # Buscar todas las predicciones PENDING del partido
    # -----------------------------------------------------

    existing = (
        supabase
        .table(
            "prediction_snapshots"
        )
        .select("*")
        .eq(
            "event_id",
            event_id
        )
        .eq(
            "result_status",
            "PENDING"
        )
        .order(
            "created_at",
            desc=True
        )
        .execute()
    )

    pending_rows = (
        existing.data
        or []
    )

    if not pending_rows:

        return {
            "updated": False,

            "reason": (
                "No existe una predicción PENDING "
                "para este event_id."
            ),

            "event_id": event_id,
        }

    # -----------------------------------------------------
    # Elegir la predicción que vamos a liquidar
    # -----------------------------------------------------

    prediction = pending_rows[0]

    # -----------------------------------------------------
    # Datos almacenados
    # -----------------------------------------------------

    features = (
        prediction.get(
            "features"
        )
        or {}
    )

    stored_game = (
        features.get(
            "game"
        )
        or {}
    )

    home_name = stored_game.get(
        "home"
    )

    away_name = stored_game.get(
        "away"
    )

    # -----------------------------------------------------
    # Determinar ganador proyectado
    # -----------------------------------------------------

    predicted_winner = determine_predicted_winner(
        prediction=prediction,
        features=features,
        actual_winner=actual_winner,
    )

    # -----------------------------------------------------
    # Normalizar ganador real
    # -----------------------------------------------------

    normalized_predicted = normalize_team_name(
        predicted_winner
    )

    normalized_actual = normalize_team_name(
        actual_winner
    )

    # -----------------------------------------------------
    # Determinar resultado
    # -----------------------------------------------------

    if (
        normalized_predicted
        and normalized_actual
        and normalized_predicted
        == normalized_actual
    ):

        prediction_result = "CORRECT"

    else:

        prediction_result = "INCORRECT"

    now = datetime.now(
        timezone.utc
    ).isoformat()

    # -----------------------------------------------------
    # Actualizar registro
    # -----------------------------------------------------

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
        .table(
            "prediction_snapshots"
        )
        .update(
            update_data
        )
        .eq(
            "id",
            prediction["id"]
        )
        .execute()
    )

    return {
        "updated": True,

        "event_id": event_id,

        "prediction_result": prediction_result,

        "predicted_winner": predicted_winner,

        "actual_winner": actual_winner,

        "actual_home_score": actual_home_score,

        "actual_away_score": actual_away_score,

        "settled_at": now,

        "prediction_id": prediction.get(
            "id"
        ),

        "model_version": prediction.get(
            "model_version"
        ),

        "data": response.data,
    }


# =========================================================
# ESTADÍSTICAS DE RENDIMIENTO
# =========================================================

def get_performance():
    """
    Calcula el rendimiento general y separado
    por versión del modelo.
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "prediction_snapshots"
        )
        .select("*")
        .order(
            "created_at",
            desc=True
        )
        .execute()
    )

    rows = response.data or []

    versions = sorted(
        list(
            {
                row.get(
                    "model_version"
                )
                or "unknown"
                for row in rows
            }
        )
    )

    def calculate_stats(model_rows):

        total = len(
            model_rows
        )

        pending = sum(
            1
            for row in model_rows
            if row.get(
                "result_status"
            ) == "PENDING"
        )

        settled = sum(
            1
            for row in model_rows
            if row.get(
                "result_status"
            ) == "SETTLED"
        )

        correct = sum(
            1
            for row in model_rows
            if row.get(
                "prediction_result"
            ) == "CORRECT"
        )

        incorrect = sum(
            1
            for row in model_rows
            if row.get(
                "prediction_result"
            ) == "INCORRECT"
        )

        confidences = []

        for row in model_rows:

            value = row.get(
                "confidence"
            )

            try:

                confidences.append(
                    float(value)
                )

            except (
                TypeError,
                ValueError
            ):
                pass

        data_qualities = []

        for row in model_rows:

            value = row.get(
                "data_quality"
            )

            try:

                data_qualities.append(
                    float(value)
                )

            except (
                TypeError,
                ValueError
            ):
                pass

        accuracy = (
            (
                correct
                / settled
            )
            * 100
            if settled > 0
            else 0
        )

        average_confidence = (
            sum(confidences)
            / len(confidences)
            if confidences
            else 0
        )

        average_data_quality = (
            sum(data_qualities)
            / len(data_qualities)
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

    # -----------------------------------------------------
    # Rendimiento general
    # -----------------------------------------------------

    overall = calculate_stats(
        rows
    )

    # -----------------------------------------------------
    # Rendimiento por modelo
    # -----------------------------------------------------

    models = {}

    for version in versions:

        model_rows = [
            row
            for row in rows
            if (
                row.get(
                    "model_version"
                )
                or "unknown"
            ) == version
        ]

        models[version] = (
            calculate_stats(
                model_rows
            )
        )

    return {
        "success": True,

        "model": {
            "versions": versions,

            "current": CURRENT_MODEL_VERSION,
        },

        "summary": overall,

        "models": models,

        "results": {
            "correct": overall[
                "correct_predictions"
            ],

            "incorrect": overall[
                "incorrect_predictions"
            ],

            "pending": overall[
                "pending_predictions"
            ],
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
        .table(
            "prediction_snapshots"
        )
        .select("*")
        .order(
            "created_at",
            desc=True
        )
        .execute()
    )

    rows = response.data or []

    predictions = []

    for row in rows:

        features = (
            row.get(
                "features"
            )
            or {}
        )

        game = (
            features.get(
                "game"
            )
            or {}
        )

        prediction = features.get(
            "predicted_winner"
        )

        home_probability = (
            row.get(
                "home_probability"
            )
        )

        away_probability = (
            row.get(
                "away_probability"
            )
        )

        # -------------------------------------------------
        # Reconstruir ganador
        # -------------------------------------------------

        if prediction is None:

            home_name = game.get(
                "home"
            )

            away_name = game.get(
                "away"
            )

            home_probability_value = safe_float(
                home_probability
            )

            away_probability_value = safe_float(
                away_probability
            )

            if (
                home_name
                and away_name
                and home_probability_value is not None
                and away_probability_value is not None
            ):

                if (
                    home_probability_value
                    >= away_probability_value
                ):

                    prediction = home_name

                else:

                    prediction = away_name

        predictions.append(
            {
                "id": row.get(
                    "id"
                ),

                "event_id": row.get(
                    "event_id"
                ),

                "model_version": row.get(
                    "model_version"
                ),

                "created_at": row.get(
                    "created_at"
                ),

                "data_cutoff": row.get(
                    "data_cutoff"
                ),

                "game": {
                    "date": game.get(
                        "date"
                    ),

                    "status": game.get(
                        "status"
                    ),

                    "detailed_status": game.get(
                        "detailed_status"
                    ),

                    "venue": game.get(
                        "venue"
                    ),

                    "home": game.get(
                        "home"
                    ),

                    "away": game.get(
                        "away"
                    ),

                    "home_team_id": game.get(
                        "home_team_id"
                    ),

                    "away_team_id": game.get(
                        "away_team_id"
                    ),
                },

                "prediction": {
                    "predicted_winner": prediction,

                    "home_probability": (
                        home_probability
                    ),

                    "away_probability": (
                        away_probability
                    ),

                    "confidence": row.get(
                        "confidence"
                    ),

                    "data_quality": row.get(
                        "data_quality"
                    ),
                },

                "result": {
                    "status": row.get(
                        "result_status"
                    ),

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

        "total": len(
            predictions
        ),

        "predictions": predictions,
    }
