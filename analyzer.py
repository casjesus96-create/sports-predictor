import requests
from datetime import datetime, timezone

from prediction import analyze_game


# =========================================================
# CONFIGURACIÓN MLB
# =========================================================

MLB_API = "https://statsapi.mlb.com/api/v1"
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1"

MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0",
    "Accept": "application/json",
}

MODEL_VERSION = "2.0.0-matchup"


# =========================================================
# UTILIDADES
# =========================================================

def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=30,
        headers=MLB_HEADERS,
    )

    response.raise_for_status()

    return response.json()


def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp(value, minimum=0.05, maximum=0.95):
    return max(
        minimum,
        min(maximum, value),
    )


# =========================================================
# PARTIDO MLB
# =========================================================

def get_game(game_id):
    """
    Obtiene el feed completo de MLB.

    Se utiliza API v1.1 porque el feed live contiene la
    información de gameData y liveData que necesitamos.
    """

    game_id = safe_int(game_id)

    if game_id is None:
        raise ValueError("game_id inválido.")

    url = f"{MLB_GAME_API}/game/{game_id}/feed/live"

    return get_json(url)


# =========================================================
# ESTADO Y DATOS BÁSICOS DEL PARTIDO
# =========================================================

def extract_game_context(feed, game_id):
    game_data = feed.get("gameData") or {}

    status_data = game_data.get("status") or {}
    teams = game_data.get("teams") or {}

    home = teams.get("home") or {}
    away = teams.get("away") or {}

    home_id = safe_int(home.get("id"))
    away_id = safe_int(away.get("id"))

    home_name = home.get("name")
    away_name = away.get("name")

    game_datetime = (
        game_data.get("datetime") or {}
    ).get("dateTime")

    venue = (
        game_data.get("venue") or {}
    ).get("name")

    return {
        "game_id": str(game_id),
        "date": game_datetime,
        "status": status_data.get("abstractGameState"),
        "detailed_status": status_data.get("detailedState"),
        "venue": venue,
        "home": home_name,
        "away": away_name,
        "home_team_id": home_id,
        "away_team_id": away_id,
    }


# =========================================================
# NORMALIZACIÓN DE FACTORES PARA EL REPOSITORIO
# =========================================================

def build_factors(analysis):
    """
    Convierte el resultado del modelo 2.0 en un bloque de
    factores cómodo para Supabase y para el frontend.

    Se conserva el matchup completo para que podamos estudiar
    posteriormente qué factores estuvieron presentes en cada
    predicción acertada o incorrecta.
    """

    matchup = analysis.get("matchup") or {}
    signals = analysis.get("signals") or {}

    context = matchup.get("general_context") or {}
    home_context = context.get("home") or {}
    away_context = context.get("away") or {}

    splits = matchup.get("batting_splits") or {}
    home_split = (
        splits.get("home_team") or {}
    ).get("batting_split") or {}
    away_split = (
        splits.get("away_team") or {}
    ).get("batting_split") or {}

    pitchers = matchup.get("pitchers") or {}
    home_pitcher = pitchers.get("home") or {}
    away_pitcher = pitchers.get("away") or {}

    h2h = matchup.get("h2h") or {}

    return {
        "model": MODEL_VERSION,

        "signals": signals,

        "weights": analysis.get("weights") or {},

        "recent_form": {
            "home": home_context,
            "away": away_context,
        },

        "h2h": h2h,

        "pitchers": {
            "home": home_pitcher,
            "away": away_pitcher,
        },

        "pitcher_hands": matchup.get(
            "pitcher_hands"
        ) or {},

        "batting_splits": {
            "home": home_split,
            "away": away_split,
        },

        # -------------------------------------------------
        # FACTORES DESTACADOS
        # -------------------------------------------------
        # Estos campos permiten que el frontend pueda
        # mostrarlos directamente sin tener que interpretar
        # todo el JSON del matchup.
        # -------------------------------------------------

        "offensive_volume": {
            "home_hits": home_split.get("hits"),
            "away_hits": away_split.get("hits"),
            "home_home_runs": home_split.get("home_runs"),
            "away_home_runs": away_split.get("home_runs"),
            "home_runs": home_split.get("runs"),
            "away_runs": away_split.get("runs"),
            "home_walks": home_split.get("walks"),
            "away_walks": away_split.get("walks"),
            "home_strikeouts": home_split.get("strikeouts"),
            "away_strikeouts": away_split.get("strikeouts"),
            "home_avg": home_split.get("avg"),
            "away_avg": away_split.get("avg"),
            "home_ops": home_split.get("ops"),
            "away_ops": away_split.get("ops"),
        },

        "form_summary": {
            "home_wins": home_context.get("wins"),
            "home_losses": home_context.get("losses"),
            "away_wins": away_context.get("wins"),
            "away_losses": away_context.get("losses"),
            "home_run_differential": home_context.get(
                "run_differential"
            ),
            "away_run_differential": away_context.get(
                "run_differential"
            ),
        },
    }


# =========================================================
# ANÁLISIS MLB PRINCIPAL
# =========================================================

def analyze_mlb_game(game_id):
    """
    Ejecuta el modelo 2.0.0-matchup para un partido MLB.

    El punto crítico contra data leakage es before_date:
    utilizamos la hora programada del partido como límite de
    información para las consultas históricas.
    """

    game_id = safe_int(game_id)

    if game_id is None:
        return {
            "success": False,
            "message": "game_id inválido.",
        }

    feed = get_game(game_id)
    game = extract_game_context(feed, game_id)

    status = game.get("status")
    detailed_status = game.get("detailed_status")

    # -----------------------------------------------------
    # PROTECCIÓN CONTRA DATA LEAKAGE
    # -----------------------------------------------------

    if status in {"Final", "Live"}:
        return {
            "success": False,
            "message": (
                "Este partido ya comenzó o terminó. "
                "El modelo pregame no utilizará información "
                "posterior al inicio del partido."
            ),
            "game_id": str(game_id),
            "status": status,
            "detailed_status": detailed_status,
        }

    home_id = game.get("home_team_id")
    away_id = game.get("away_team_id")

    if home_id is None or away_id is None:
        return {
            "success": False,
            "message": (
                "MLB no proporcionó correctamente los IDs "
                "de los equipos del partido."
            ),
            "game_id": str(game_id),
        }

    before_date = game.get("date")

    if not before_date:
        before_date = datetime.now(
            timezone.utc
        ).isoformat()

    try:
        analysis = analyze_game(
            game_id=str(game_id),
            home_team_id=home_id,
            away_team_id=away_id,
            before_date=before_date,
            season=datetime.fromisoformat(
                before_date.replace("Z", "+00:00")
            ).year,
            game_type="R",
        )

    except Exception as exc:
        return {
            "success": False,
            "message": (
                "No fue posible ejecutar el modelo "
                "2.0.0-matchup."
            ),
            "error": str(exc),
            "game_id": str(game_id),
        }

    if not analysis.get("success"):
        return analysis

    prediction = analysis.get("prediction") or {}
    matchup = analysis.get("matchup") or {}
    signals = analysis.get("signals") or {}

    home_probability = safe_float(
        prediction.get("home_probability"),
        0.5,
    )

    away_probability = safe_float(
        prediction.get("away_probability"),
        0.5,
    )

    # -----------------------------------------------------
    # CONFIANZA
    # -----------------------------------------------------

    probability_difference = abs(
        home_probability - away_probability
    )

    confidence = clamp(
        0.50 + probability_difference * 0.50,
        0.50,
        0.95,
    )

    data_quality = safe_int(
        prediction.get("data_quality"),
        0,
    )

    projected_side = prediction.get(
        "projected_side"
    )

    predicted_team = (
        game.get("home")
        if projected_side == "home"
        else game.get("away")
    )

    factors = build_factors(analysis)

    # -----------------------------------------------------
    # RESPUESTA COMPATIBLE CON repository.py
    # -----------------------------------------------------

    return {
        "success": True,

        "model_version": MODEL_VERSION,

        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "game": game,

        "prediction": {
            "winner": predicted_team,
            "projected_side": projected_side,
            "home_probability": round(
                home_probability,
                4,
            ),
            "away_probability": round(
                away_probability,
                4,
            ),
            "confidence": round(
                confidence,
                4,
            ),
            "data_quality": data_quality,
        },

        "signals": signals,

        "factors": factors,

        "matchup": matchup,
    }


# =========================================================
# COMPATIBILIDAD CON EL BASELINE ANTERIOR
# =========================================================

def baseline_prediction():
    """
    Mantiene la función histórica para no romper tests o
    integraciones antiguas.
    """

    probability = 1.0 / (
        1.0 + __import__("math").exp(-0.15)
    )

    return {
        "home_probability": round(
            probability,
            6,
        ),
        "away_probability": round(
            1.0 - probability,
            6,
        ),
        "confidence": "Inicial",
        "data_quality": 72,
        "features": {
            "note": (
                "Baseline experimental conservado "
                "por compatibilidad."
            ),
        },
    }
