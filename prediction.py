import math
from datetime import datetime, timezone

from matchup_engine import get_matchup_data


# =========================================================
# CONFIGURACIÓN DEL MODELO
# =========================================================

MODEL_VERSION = "2.0.0-matchup"

# Pesos iniciales.
#
# IMPORTANTE:
# Estos pesos son experimentales.
# Posteriormente los calibraremos utilizando resultados reales.
#
WEIGHTS = {
    "general_form": 0.22,
    "batting_split": 0.22,
    "h2h": 0.12,
    "run_differential": 0.14,
    "pitcher": 0.20,
    "home_advantage": 0.10,
}


# =========================================================
# UTILIDADES
# =========================================================

def clamp(value, minimum=0.05, maximum=0.95):
    return max(
        minimum,
        min(maximum, value),
    )


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def sigmoid(value):
    """
    Convierte una señal matemática en un valor
    entre 0 y 1.
    """

    try:
        return 1.0 / (1.0 + math.exp(-value))
    except OverflowError:
        return 0.0 if value < 0 else 1.0


# =========================================================
# FORMA RECIENTE
# =========================================================

def calculate_recent_form(form):
    """
    Calcula la forma reciente utilizando:

        últimos 5  -> 50%
        últimos 10 -> 30%
        últimos 15 -> 20%
    """

    last_5 = form.get("last_5", {})
    last_10 = form.get("last_10", {})
    last_15 = form.get("last_15", {})

    win_5 = safe_float(
        last_5.get("win_rate"),
        0.50,
    )

    win_10 = safe_float(
        last_10.get("win_rate"),
        0.50,
    )

    win_15 = safe_float(
        last_15.get("win_rate"),
        0.50,
    )

    return (
        win_5 * 0.50
        + win_10 * 0.30
        + win_15 * 0.20
    )


def calculate_run_differential(form):
    """
    Diferencial de carreras por partido.
    """

    values = []

    for key in (
        "last_5",
        "last_10",
        "last_15",
    ):

        data = form.get(key, {})

        games = safe_float(
            data.get("games"),
            0,
        )

        differential = safe_float(
            data.get("run_differential"),
            0,
        )

        if games > 0:
            values.append(
                differential / games
            )
        else:
            values.append(0.0)

    return (
        values[0] * 0.50
        + values[1] * 0.30
        + values[2] * 0.20
    )


# =========================================================
# H2H
# =========================================================

def calculate_h2h_signal(h2h):
    """
    Convierte el H2H en una señal centrada alrededor
    de 0.

    > 0  favorece al equipo local
    < 0  favorece al visitante
    """

    if not h2h.get("available"):
        return 0.0

    games = safe_int(
        h2h.get("games"),
        0,
    )

    if games <= 0:
        return 0.0

    home_wins = safe_int(
        h2h.get("home_team_wins"),
        0,
    )

    away_wins = safe_int(
        h2h.get("away_team_wins"),
        0,
    )

    win_difference = (
        home_wins - away_wins
    ) / games

    # Limitamos la influencia del H2H.
    return max(
        -1.0,
        min(1.0, win_difference),
    )


# =========================================================
# SPLITS OFENSIVOS
# =========================================================

def calculate_split_signal(
    home_split,
    away_split,
):
    """
    Compara el rendimiento ofensivo de cada equipo
    contra la mano del pitcher que realmente enfrentará.

    Utiliza principalmente OPS.

    También incorpora AVG, OBP y SLG.
    """

    home_available = (
        home_split.get("available", False)
    )

    away_available = (
        away_split.get("available", False)
    )

    if not home_available and not away_available:
        return 0.0

    def offensive_score(split):

        if not split.get("available"):
            return 0.700

        ops = safe_float(
            split.get("ops"),
            0.700,
        )

        avg = safe_float(
            split.get("avg"),
            0.250,
        )

        obp = safe_float(
            split.get("obp"),
            0.320,
        )

        slg = safe_float(
            split.get("slg"),
            0.400,
        )

        # Normalizamos alrededor de valores MLB razonables.
        ops_component = (
            (ops - 0.700) / 0.200
        )

        avg_component = (
            (avg - 0.250) / 0.050
        )

        obp_component = (
            (obp - 0.320) / 0.050
        )

        slg_component = (
            (slg - 0.400) / 0.100
        )

        return (
            ops_component * 0.55
            + avg_component * 0.15
            + obp_component * 0.15
            + slg_component * 0.15
        )

    home_score = offensive_score(
        home_split
    )

    away_score = offensive_score(
        away_split
    )

    difference = (
        home_score - away_score
    )

    return math.tanh(
        difference / 2.0
    )


# =========================================================
# CONTEXTO GENERAL
# =========================================================

def calculate_general_context_signal(
    home_context,
    away_context,
):
    """
    Compara win rate y diferencial de carreras.
    """

    home_win_rate = safe_float(
        home_context.get("win_rate"),
        0.500,
    )

    away_win_rate = safe_float(
        away_context.get("win_rate"),
        0.500,
    )

    win_difference = (
        home_win_rate
        - away_win_rate
    )

    home_run_diff = safe_float(
        home_context.get(
            "run_differential"
        ),
        0,
    )

    away_run_diff = safe_float(
        away_context.get(
            "run_differential"
        ),
        0,
    )

    home_games = max(
        safe_int(
            home_context.get("games"),
            1,
        ),
        1,
    )

    away_games = max(
        safe_int(
            away_context.get("games"),
            1,
        ),
        1,
    )

    home_run_per_game = (
        home_run_diff / home_games
    )

    away_run_per_game = (
        away_run_diff / away_games
    )

    run_difference = (
        home_run_per_game
        - away_run_per_game
    )

    run_signal = math.tanh(
        run_difference / 2.0
    )

    win_signal = math.tanh(
        win_difference * 4.0
    )

    return (
        win_signal * 0.60
        + run_signal * 0.40
    )


# =========================================================
# PITCHERS
# =========================================================

def calculate_pitcher_signal(
    home_pitcher,
    away_pitcher,
):
    """
    Evalúa la disponibilidad de los pitchers.

    En esta etapa no inventamos estadísticas que todavía
    no estén disponibles en matchup_engine.

    Si posteriormente agregamos ERA/FIP/xFIP/WHIP/etc.,
    este componente será ampliado.
    """

    home_available = (
        home_pitcher.get("available", False)
    )

    away_available = (
        away_pitcher.get("available", False)
    )

    if (
        home_available
        and away_available
    ):
        return 0.0

    if home_available and not away_available:
        return 0.15

    if away_available and not home_available:
        return -0.15

    return 0.0


# =========================================================
# CALIDAD DE DATOS
# =========================================================

def calculate_data_quality(matchup):
    """
    Estima qué tan completa es la información disponible.

    NO representa precisión matemática del modelo.
    """

    score = 0

    # Pitchers
    pitchers = matchup.get(
        "pitchers",
        {},
    )

    home_pitcher = pitchers.get(
        "home",
        {},
    )

    away_pitcher = pitchers.get(
        "away",
        {},
    )

    if home_pitcher.get("available"):
        score += 15

    if away_pitcher.get("available"):
        score += 15

    # H2H
    h2h = matchup.get(
        "h2h",
        {},
    )

    if h2h.get("available"):
        games = safe_int(
            h2h.get("games"),
            0,
        )

        if games >= 10:
            score += 15
        elif games >= 5:
            score += 10
        elif games > 0:
            score += 5

    # Splits
    splits = matchup.get(
        "batting_splits",
        {},
    )

    home_split = (
        splits
        .get("home_team", {})
        .get("batting_split", {})
    )

    away_split = (
        splits
        .get("away_team", {})
        .get("batting_split", {})
    )

    if home_split.get("available"):
        score += 15

    if away_split.get("available"):
        score += 15

    # Contexto general
    context = matchup.get(
        "general_context",
        {},
    )

    if context.get("home", {}).get("available"):
        score += 5

    if context.get("away", {}).get("available"):
        score += 5

    return min(
        score,
        100,
    )


# =========================================================
# PROBABILIDAD
# =========================================================

def calculate_probability(
    matchup,
):
    """
    Calcula la probabilidad pregame utilizando
    los datos reales del matchup.

    La salida está expresada como:
        home_probability
        away_probability
    """

    # -----------------------------------------------------
    # DATOS
    # -----------------------------------------------------

    h2h = matchup.get(
        "h2h",
        {},
    )

    context = matchup.get(
        "general_context",
        {},
    )

    home_context = context.get(
        "home",
        {},
    )

    away_context = context.get(
        "away",
        {},
    )

    splits = matchup.get(
        "batting_splits",
        {},
    )

    home_split = (
        splits
        .get("home_team", {})
        .get("batting_split", {})
    )

    away_split = (
        splits
        .get("away_team", {})
        .get("batting_split", {})
    )

    pitchers = matchup.get(
        "pitchers",
        {},
    )

    home_pitcher = pitchers.get(
        "home",
        {},
    )

    away_pitcher = pitchers.get(
        "away",
        {},
    )

    # -----------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------

    general_signal = calculate_general_context_signal(
        home_context,
        away_context,
    )

    split_signal = calculate_split_signal(
        home_split,
        away_split,
    )

    h2h_signal = calculate_h2h_signal(
        h2h
    )

    home_run_form = calculate_run_differential(
        home_context
    )

    away_run_form = calculate_run_differential(
        away_context
    )

    run_form_difference = (
        home_run_form
        - away_run_form
    )

    run_signal = math.tanh(
        run_form_difference / 2.0
    )

    pitcher_signal = calculate_pitcher_signal(
        home_pitcher,
        away_pitcher,
    )

    # -----------------------------------------------------
    # LOCALÍA
    # -----------------------------------------------------

    home_advantage_signal = 1.0

    # -----------------------------------------------------
    # COMBINACIÓN
    # -----------------------------------------------------

    combined_signal = (

        general_signal
        * WEIGHTS["general_form"]

        + split_signal
        * WEIGHTS["batting_split"]

        + h2h_signal
        * WEIGHTS["h2h"]

        + run_signal
        * WEIGHTS["run_differential"]

        + pitcher_signal
        * WEIGHTS["pitcher"]

        + home_advantage_signal
        * WEIGHTS["home_advantage"]
    )

    # -----------------------------------------------------
    # ESCALA
    # -----------------------------------------------------

    probability_home = sigmoid(
        combined_signal * 2.0
    )

    probability_home = clamp(
        probability_home,
        0.05,
        0.95,
    )

    probability_away = (
        1.0 - probability_home
    )

    return {
        "home_probability": round(
            probability_home,
            4,
        ),

        "away_probability": round(
            probability_away,
            4,
        ),

        "signals": {
            "general_context": round(
                general_signal,
                4,
            ),

            "batting_split": round(
                split_signal,
                4,
            ),

            "h2h": round(
                h2h_signal,
                4,
            ),

            "run_differential": round(
                run_signal,
                4,
            ),

            "pitcher": round(
                pitcher_signal,
                4,
            ),

            "home_advantage": round(
                home_advantage_signal,
                4,
            ),
        },
    }


# =========================================================
# ANÁLISIS COMPLETO
# =========================================================

def analyze_game(
    game_id,
    home_team_id,
    away_team_id,
    before_date=None,
    season=None,
    game_type="R",
):
    """
    Ejecuta el análisis completo del partido.

    IMPORTANTE:
    before_date representa el momento límite de información.

    El modelo no debe utilizar información posterior
    a esa fecha.
    """

    matchup = get_matchup_data(
        game_id=game_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        before_date=before_date,
        season=season,
        game_type=game_type,
    )

    probabilities = calculate_probability(
        matchup
    )

    home_probability = (
        probabilities["home_probability"]
    )

    away_probability = (
        probabilities["away_probability"]
    )

    confidence = (
        abs(
            home_probability
            - away_probability
        )
    )

    # No llamamos "precisión".
    # Es solamente una medida interna de separación
    # entre las probabilidades.
    confidence_score = round(
        0.50
        + confidence * 0.50,
        4,
    )

    data_quality = calculate_data_quality(
        matchup
    )

    if home_probability >= away_probability:
        projected_side = "home"
    else:
        projected_side = "away"

    game = matchup.get(
        "game",
        {},
    )

    return {
        "success": True,

        "model_version":
            MODEL_VERSION,

        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "game": {
            "game_id": str(
                game_id
            ),

            "home_team_id":
                home_team_id,

            "away_team_id":
                away_team_id,

            "before_date":
                before_date,

            "season":
                matchup.get(
                    "season"
                ),
        },

        "prediction": {

            "projected_side":
                projected_side,

            "home_probability":
                home_probability,

            "away_probability":
                away_probability,

            "confidence":
                confidence_score,

            "data_quality":
                data_quality,
        },

        "signals":
            probabilities["signals"],

        "matchup":
            matchup,
    }


# =========================================================
# COMPATIBILIDAD CON EL BASELINE ANTERIOR
# =========================================================

def baseline_prediction():
    """
    Mantiene funcionando el test antiguo.

    Esto se conserva temporalmente para evitar romper
    otras partes de la aplicación mientras migramos
    al nuevo motor.
    """

    probability = (
        1.0
        / (
            1.0
            + math.exp(-0.15)
        )
    )

    return {
        "home_probability":
            round(
                probability,
                6,
            ),

        "away_probability":
            round(
                1.0 - probability,
                6,
            ),

        "confidence":
            "Inicial",

        "data_quality":
            72,

        "features": {
            "note":
                "Baseline experimental; "
                "historical features not yet connected."
        },
    }
