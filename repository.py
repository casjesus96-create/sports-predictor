from datetime import datetime, timezone
import os
import unicodedata
import re

import requests

from supabase import create_client, Client


# =========================================================
# CONFIGURACIÓN DEL MODELO
# =========================================================

CURRENT_MODEL_VERSION = "1.2.0-form"

MLB_API = "https://statsapi.mlb.com/api/v1"

MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0"
}


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
    Normaliza un nombre de equipo para comparaciones
    confiables.

    Ejemplo:

    "Chicago Cubs"
    "chicago cubs"
    "Chicago  Cubs"

    se consideran equivalentes.
    """

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    text = unicodedata.normalize(
        "NFKD",
        text
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def teams_match(team_a, team_b):
    """
    Comprueba si dos nombres representan al mismo equipo.
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


def safe_float(
    value,
    default=None
):
    """
    Conversión segura a float.
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


# =========================================================
# DETERMINAR GANADOR PROYECTADO
# =========================================================

def determine_predicted_winner(
    prediction,
    features,
    actual_winner=None,
):
    """
    Determina el ganador que originalmente proyectó
    el modelo.

    Prioridad:

    1. Ganador almacenado en features.
    2. Ganador reconstruido mediante probabilidades.
    3. None.
    """

    prediction = prediction or {}

    features = features or {}

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
    # Ganador guardado
    # -----------------------------------------------------

    if stored_winner:

        if (
            home_name
            and teams_match(
                stored_winner,
                home_name
            )
        ):
            return home_name

        if (
            away_name
            and teams_match(
                stored_winner,
                away_name
            )
        ):
            return away_name

    # -----------------------------------------------------
    # Reconstruir mediante probabilidades
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
    # Último recurso
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

    data_quality = prediction.get(
        "data_quality"
    )

    if data_quality is None:
        data_quality = 0

    features = {
        "game": game,

        "factors": factors,

        "predicted_winner": prediction.get(
            "winner"
        ),
    }

    payload = {
        "event_id": str(event_id),

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
    Obtiene las predicciones pendientes.
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
    Liquida una predicción PENDING.
    """

    supabase = get_supabase_client()

    event_id = str(
        event_id
    )

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

    prediction = pending_rows[0]

    features = (
        prediction.get(
            "features"
        )
        or {}
    )

    predicted_winner = determine_predicted_winner(
        prediction=prediction,
        features=features,
        actual_winner=actual_winner,
    )

    normalized_predicted = normalize_team_name(
        predicted_winner
    )

    normalized_actual = normalize_team_name(
        actual_winner
    )

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
# OBTENER RESULTADO OFICIAL MLB
# =========================================================

def get_official_mlb_result(
    event_id
):
    """
    Consulta MLB y obtiene el resultado oficial
    de un partido.

    No modifica la base de datos.
    """

    event_id = str(
        event_id
    )

    url = f"{MLB_API}/schedule"

    params = {
        "sportId": 1,
        "gamePk": event_id,
    }

    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers=MLB_HEADERS,
    )

    response.raise_for_status()

    data = response.json()

    games = []

    for date_block in data.get(
        "dates",
        []
    ):

        games.extend(
            date_block.get(
                "games",
                []
            )
        )

    target_game = None

    for game in games:

        if str(
            game.get("gamePk")
        ) == event_id:

            target_game = game

            break

    if target_game is None:

        return {
            "success": False,

            "event_id": event_id,

            "status": "NOT_FOUND",

            "message": (
                "MLB no encontró este gamePk."
            ),
        }

    status = (
        target_game.get(
            "status"
        )
        or {}
    )

    abstract_state = status.get(
        "abstractGameState"
    )

    detailed_state = status.get(
        "detailedState"
    )

    teams = (
        target_game.get(
            "teams"
        )
        or {}
    )

    home = (
        teams.get(
            "home"
        )
        or {}
    )

    away = (
        teams.get(
            "away"
        )
        or {}
    )

    home_team = (
        home.get(
            "team"
        )
        or {}
    )

    away_team = (
        away.get(
            "team"
        )
        or {}
    )

    home_name = home_team.get(
        "name"
    )

    away_name = away_team.get(
        "name"
    )

    home_score = home.get(
        "score"
    )

    away_score = away.get(
        "score"
    )

    if abstract_state != "Final":

        return {
            "success": False,

            "event_id": event_id,

            "status": abstract_state,

            "detailed_status": detailed_state,

            "home": home_name,

            "away": away_name,

            "home_score": home_score,

            "away_score": away_score,

            "message": (
                "El partido todavía no está Final."
            ),
        }

    if (
        home_score is None
        or away_score is None
    ):

        return {
            "success": False,

            "event_id": event_id,

            "status": "Final",

            "home": home_name,

            "away": away_name,

            "message": (
                "El partido aparece como Final, "
                "pero MLB no proporcionó ambos marcadores."
            ),
        }

    try:

        home_score = int(
            home_score
        )

        away_score = int(
            away_score
        )

    except (
        TypeError,
        ValueError
    ):

        return {
            "success": False,

            "event_id": event_id,

            "status": "Final",

            "home": home_name,

            "away": away_name,

            "message": (
                "Los marcadores recibidos por MLB "
                "no son válidos."
            ),
        }

    if home_score > away_score:

        actual_winner = home_name

    elif away_score > home_score:

        actual_winner = away_name

    else:

        return {
            "success": False,

            "event_id": event_id,

            "status": "Final",

            "home": home_name,

            "away": away_name,

            "home_score": home_score,

            "away_score": away_score,

            "message": (
                "No fue posible determinar el ganador."
            ),
        }

    return {
        "success": True,

        "event_id": event_id,

        "status": "Final",

        "detailed_status": detailed_state,

        "home": home_name,

        "away": away_name,

        "home_score": home_score,

        "away_score": away_score,

        "actual_winner": actual_winner,
    }


# =========================================================
# REPARAR UNA PREDICCIÓN YA LIQUIDADA
# =========================================================

def repair_settled_prediction(
    event_id
):
    """
    Revisa y corrige una predicción que ya está SETTLED.

    IMPORTANTE:

    Esta función NO crea una predicción nueva.

    Únicamente vuelve a consultar el resultado oficial
    de MLB y corrige:

    - prediction_result
    - actual_winner
    - actual_home_score
    - actual_away_score
    - settled_at

    No modifica:

    - probabilidades
    - confianza
    - calidad de datos
    - modelo
    - fecha original
    - factores
    - proyección original
    """

    supabase = get_supabase_client()

    event_id = str(
        event_id
    )

    # -----------------------------------------------------
    # Buscar predicción
    # -----------------------------------------------------

    response = (
        supabase
        .table(
            "prediction_snapshots"
        )
        .select("*")
        .eq(
            "event_id",
            event_id
        )
        .order(
            "created_at",
            desc=True
        )
        .limit(1)
        .execute()
    )

    rows = (
        response.data
        or []
    )

    if not rows:

        return {
            "success": False,

            "updated": False,

            "event_id": event_id,

            "status": "PREDICTION_NOT_FOUND",

            "message": (
                "No existe ninguna predicción "
                "para este event_id."
            ),
        }

    prediction = rows[0]

    # -----------------------------------------------------
    # Consultar MLB
    # -----------------------------------------------------

    official = get_official_mlb_result(
        event_id
    )

    if not official.get(
        "success"
    ):

        return {
            "success": False,

            "updated": False,

            "event_id": event_id,

            "status": official.get(
                "status"
            ),

            "message": official.get(
                "message"
            ),

            "official": official,
        }

    # -----------------------------------------------------
    # Recuperar proyección original
    # -----------------------------------------------------

    features = (
        prediction.get(
            "features"
        )
        or {}
    )

    predicted_winner = determine_predicted_winner(
        prediction=prediction,
        features=features,
        actual_winner=official.get(
            "actual_winner"
        ),
    )

    actual_winner = official.get(
        "actual_winner"
    )

    # -----------------------------------------------------
    # Comparación robusta
    # -----------------------------------------------------

    if teams_match(
        predicted_winner,
        actual_winner
    ):

        prediction_result = "CORRECT"

    else:

        prediction_result = "INCORRECT"

    now = datetime.now(
        timezone.utc
    ).isoformat()

    # -----------------------------------------------------
    # Datos que se corregirán
    # -----------------------------------------------------

    update_data = {
        "result_status": "SETTLED",

        "prediction_result": prediction_result,

        "actual_winner": actual_winner,

        "actual_home_score": official.get(
            "home_score"
        ),

        "actual_away_score": official.get(
            "away_score"
        ),

        "settled_at": now,
    }

    # -----------------------------------------------------
    # Actualizar
    # -----------------------------------------------------

    updated = (
        supabase
        .table(
            "prediction_snapshots"
        )
        .update(
            update_data
        )
        .eq(
            "id",
            prediction.get("id")
        )
        .execute()
    )

    previous_result = prediction.get(
        "prediction_result"
    )

    return {
        "success": True,

        "updated": True,

        "changed": (
            previous_result
            != prediction_result
        ),

        "event_id": event_id,

        "prediction_id": prediction.get(
            "id"
        ),

        "model_version": prediction.get(
            "model_version"
        ),

        "predicted_winner": predicted_winner,

        "actual_winner": actual_winner,

        "prediction_result": prediction_result,

        "previous_prediction_result": previous_result,

        "home": official.get(
            "home"
        ),

        "away": official.get(
            "away"
        ),

        "home_score": official.get(
            "home_score"
        ),

        "away_score": official.get(
            "away_score"
        ),

        "settled_at": now,

        "data": updated.data,
    }


# =========================================================
# REPARAR TODAS LAS PREDICCIONES LIQUIDADAS
# =========================================================

def repair_all_settled_predictions():
    """
    Revisa todas las predicciones SETTLED.

    Cada registro se contrasta nuevamente contra
    el resultado oficial de MLB.

    No crea predicciones nuevas.
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "prediction_snapshots"
        )
        .select(
            "id,event_id,model_version,"
            "result_status,prediction_result,"
            "created_at"
        )
        .eq(
            "result_status",
            "SETTLED"
        )
        .order(
            "created_at",
            desc=False
        )
        .execute()
    )

    rows = (
        response.data
        or []
    )

    results = []

    repaired_count = 0
    unchanged_count = 0
    failed_count = 0

    for row in rows:

        event_id = row.get(
            "event_id"
        )

        if not event_id:

            failed_count += 1

            results.append(
                {
                    "success": False,

                    "updated": False,

                    "status": "INVALID_EVENT_ID",

                    "message": (
                        "La predicción no tiene event_id."
                    ),

                    "prediction_id": row.get(
                        "id"
                    ),
                }
            )

            continue

        try:

            result = repair_settled_prediction(
                event_id
            )

            results.append(
                result
            )

            if result.get(
                "success"
            ):

                if result.get(
                    "changed"
                ):

                    repaired_count += 1

                else:

                    unchanged_count += 1

            else:

                failed_count += 1

        except Exception as exc:

            failed_count += 1

            results.append(
                {
                    "success": False,

                    "updated": False,

                    "event_id": str(
                        event_id
                    ),

                    "status": "ERROR",

                    "message": str(
                        exc
                    ),
                }
            )

    return {
        "success": True,

        "total": len(rows),

        "repaired": repaired_count,

        "unchanged": unchanged_count,

        "failed": failed_count,

        "results": results,
    }


# =========================================================
# ESTADÍSTICAS DE RENDIMIENTO
# =========================================================

def get_performance():
    """
    Calcula el rendimiento general y por modelo.
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

    def calculate_stats(
        model_rows
    ):

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

    overall = calculate_stats(
        rows
    )

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
    en un formato limpio para la interfaz.
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

        home_probability = row.get(
            "home_probability"
        )

        away_probability = row.get(
            "away_probability"
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
