import math


MODEL_VERSION = "NFL-1.0.0"


def clamp(value, low=0.05, high=0.95):
    """
    Limita un valor a un rango seguro.
    """
    return max(low, min(high, value))


def _float_value(value, default=0.0):
    """
    Convierte un valor a float de forma segura.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sigmoid(value):
    """
    Función logística estable.
    """
    bounded = max(-8.0, min(8.0, value))
    return 1.0 / (1.0 + math.exp(-bounded))


def calculate_probability(
    home_history,
    away_history,
    rest_home_days,
    rest_away_days,
):
    """
    Calcula la probabilidad pregame del equipo local.

    Modelo oficial:
    NFL-1.0.0

    Factores utilizados:
    - Diferencial de puntos de temporada
    - Producción ofensiva/defensiva
    - Diferencial de puntos reciente
    - Win rate reciente
    - Diferencia de descanso
    - Ventaja de localía

    Importante:
    Esta función solamente utiliza los datos que recibe del analizador.
    La validación del cutoff pregame corresponde a nfl_analyzer.py.
    """

    # ---------------------------------------------------------
    # Datos de temporada
    # ---------------------------------------------------------

    home_point_diff = _float_value(
        home_history.get("point_diff_per_game")
    )

    away_point_diff = _float_value(
        away_history.get("point_diff_per_game")
    )

    home_points_for = _float_value(
        home_history.get("points_for_per_game"),
        21.0,
    )

    away_points_for = _float_value(
        away_history.get("points_for_per_game"),
        21.0,
    )

    home_points_against = _float_value(
        home_history.get("points_against_per_game"),
        21.0,
    )

    away_points_against = _float_value(
        away_history.get("points_against_per_game"),
        21.0,
    )

    # ---------------------------------------------------------
    # Forma reciente
    # ---------------------------------------------------------

    home_recent_point_diff = _float_value(
        home_history.get("recent_point_diff_per_game")
    )

    away_recent_point_diff = _float_value(
        away_history.get("recent_point_diff_per_game")
    )

    home_recent_win_rate = _float_value(
        home_history.get("recent_win_rate"),
        0.5,
    )

    away_recent_win_rate = _float_value(
        away_history.get("recent_win_rate"),
        0.5,
    )

    # ---------------------------------------------------------
    # Descanso
    # ---------------------------------------------------------

    home_rest = _float_value(rest_home_days, 7.0)
    away_rest = _float_value(rest_away_days, 7.0)

    rest_difference = math.tanh(
        (home_rest - away_rest) / 3.0
    )

    # ---------------------------------------------------------
    # Componentes del modelo
    # ---------------------------------------------------------

    season_point_differential = math.tanh(
        (home_point_diff - away_point_diff) / 10.0
    )

    scoring_defense = math.tanh(
        (
            (home_points_for - away_points_for)
            - (home_points_against - away_points_against)
        )
        / 14.0
    )

    recent_point_differential = math.tanh(
        (home_recent_point_diff - away_recent_point_diff)
        / 10.0
    )

    recent_win_rate_difference = (
        home_recent_win_rate - away_recent_win_rate
    )

    # ---------------------------------------------------------
    # Señal final
    # ---------------------------------------------------------

    signal = (
        season_point_differential * 0.38
        + scoring_defense * 0.28
        + recent_point_differential * 0.16
        + recent_win_rate_difference * 0.10
        + rest_difference * 0.03
        + 0.05
    )

    # ---------------------------------------------------------
    # Probabilidad
    # ---------------------------------------------------------

    home_probability = clamp(
        _sigmoid(signal * 2.2)
    )

    away_probability = 1.0 - home_probability

    return {
        "home": round(home_probability, 4),
        "away": round(away_probability, 4),
    }


def calculate_confidence(probabilities):
    """
    Calcula la confianza reportada por el modelo.

    En NFL-1.0.0 la confianza NO se presenta como una métrica
    de calibración estadística todavía, porque aún no existe una
    muestra suficiente de predicciones liquidadas para calibrarla.

    Por ahora se utiliza la probabilidad del resultado más probable
    como medida transparente de confianza.

    Cuando tengamos suficientes predicciones liquidadas podremos
    sustituir esta representación por una calibración estadística
    basada en resultados reales, sin crear otro modelo paralelo.
    """

    home_probability = _float_value(
        probabilities.get("home"),
        0.5,
    )

    away_probability = _float_value(
        probabilities.get("away"),
        0.5,
    )

    confidence = max(
        home_probability,
        away_probability,
    )

    return round(
        clamp(confidence, 0.50, 0.95),
        4,
    )
