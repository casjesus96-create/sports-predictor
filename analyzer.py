import math
import requests
from datetime import datetime, timezone

from form_engine import get_matchup_form


# =========================================================
# MLB API
# =========================================================

MLB_API = "https://statsapi.mlb.com/api/v1"

# El feed completo de partidos utiliza v1.1
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1"


MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0",
    "Accept": "application/json",
}


# =========================================================
# UTILIDADES
# =========================================================

def clamp(
    value,
    minimum=0.05,
    maximum=0.95
):
    return max(
        minimum,
        min(maximum, value)
    )


def get_json(
    url,
    params=None
):
    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers=MLB_HEADERS,
    )

    response.raise_for_status()

    return response.json()


def safe_float(
    value,
    default=None
):
    try:
        return float(value)

    except (
        TypeError,
        ValueError
    ):
        return default


# =========================================================
# PARTIDO MLB
# =========================================================

def get_game(
    game_id
):
    """
    Obtiene el feed completo del partido.

    El endpoint del feed utiliza API v1.1.
    """

    url = (
        f"{MLB_GAME_API}"
        f"/game/{game_id}/feed/live"
    )

    return get_json(url)


# =========================================================
# ESTADÍSTICAS DEL EQUIPO
# =========================================================

def get_team_season_stats(
    team_id,
    season=2026
):
    """
    Obtiene estadísticas de temporada
    de bateo y pitcheo.
    """

    url = (
        f"{MLB_API}"
        f"/teams/{team_id}/stats"
    )

    params = {
        "stats": "season",
        "group": "hitting,pitching",
        "season": season,
    }

    data = get_json(
        url,
        params
    )

    result = {
        "hitting": {},
        "pitching": {},
    }

    for split in data.get(
        "stats",
        []
    ):

        group = (
            split
            .get(
                "group",
                {}
            )
            .get(
                "displayName",
                ""
            )
            .lower()
        )

        splits = split.get(
            "splits",
            []
        )

        if not splits:
            continue

        stats = splits[0].get(
            "stat",
            {}
        )

        if group == "hitting":

            result["hitting"] = stats

        elif group == "pitching":

            result["pitching"] = stats

    return result


# =========================================================
# ESTADÍSTICAS DEL PITCHER
# =========================================================

def get_player_pitching_stats(
    player_id,
    season=2026
):
    """
    Obtiene estadísticas de temporada
    del pitcher probable.
    """

    if not player_id:
        return {}

    url = (
        f"{MLB_API}"
        f"/people/{player_id}/stats"
    )

    params = {
        "stats": "season",
        "group": "pitching",
        "season": season,
    }

    data = get_json(
        url,
        params
    )

    splits = (
        data
        .get(
            "stats",
            [{}]
        )[0]
        .get(
            "splits",
            []
        )
    )

    if not splits:
        return {}

    return splits[0].get(
        "stat",
        {}
    )


# =========================================================
# FORMA RECIENTE
# =========================================================

def calculate_recent_form_score(
    form
):
    """
    Calcula una señal de forma reciente.

    Peso:
    últimos 5  = 50%
    últimos 10 = 30%
    últimos 15 = 20%
    """

    last_5 = form.get(
        "last_5",
        {}
    )

    last_10 = form.get(
        "last_10",
        {}
    )

    last_15 = form.get(
        "last_15",
        {}
    )

    win_rate_5 = safe_float(
        last_5.get(
            "win_rate"
        ),
        0.5
    )

    win_rate_10 = safe_float(
        last_10.get(
            "win_rate"
        ),
        0.5
    )

    win_rate_15 = safe_float(
        last_15.get(
            "win_rate"
        ),
        0.5
    )

    weighted_win_rate = (
        win_rate_5 * 0.50
        + win_rate_10 * 0.30
        + win_rate_15 * 0.20
    )

    return weighted_win_rate


def calculate_run_form_score(
    form
):
    """
    Calcula el diferencial de carreras
    por partido utilizando 5/10/15.
    """

    last_5 = form.get(
        "last_5",
        {}
    )

    last_10 = form.get(
        "last_10",
        {}
    )

    last_15 = form.get(
        "last_15",
        {}
    )

    diff_5 = safe_float(
        last_5.get(
            "run_differential"
        ),
        0
    )

    games_5 = safe_float(
        last_5.get(
            "games"
        ),
        0
    )

    diff_10 = safe_float(
        last_10.get(
            "run_differential"
        ),
        0
    )

    games_10 = safe_float(
        last_10.get(
            "games"
        ),
        0
    )

    diff_15 = safe_float(
        last_15.get(
            "run_differential"
        ),
        0
    )

    games_15 = safe_float(
        last_15.get(
            "games"
        ),
        0
    )

    per_game_5 = (
        diff_5 / games_5
        if games_5 > 0
        else 0
    )

    per_game_10 = (
        diff_10 / games_10
        if games_10 > 0
        else 0
    )

    per_game_15 = (
        diff_15 / games_15
        if games_15 > 0
        else 0
    )

    weighted_run_diff = (
        per_game_5 * 0.50
        + per_game_10 * 0.30
        + per_game_15 * 0.20
    )

    return weighted_run_diff


# =========================================================
# MODELO DE PROBABILIDAD
# =========================================================

def calculate_probability(
    home_hitting,
    away_hitting,
    home_pitching,
    away_pitching,
    home_pitcher,
    away_pitcher,
    home_form,
    away_form
):
    """
    Calcula la probabilidad pregame.

    Componentes:

    1. OPS
    2. ERA de equipos
    3. ERA de pitchers probables
    4. Ventaja de local
    5. Forma reciente
    6. Diferencial de carreras
    """

    home_score = 0.50

    # -------------------------------------------------
    # 1. OFENSIVA
    # -------------------------------------------------

    home_ops = safe_float(
        home_hitting.get(
            "ops"
        ),
        0.700
    )

    away_ops = safe_float(
        away_hitting.get(
            "ops"
        ),
        0.700
    )

    offensive_difference = (
        home_ops - away_ops
    )

    home_score += (
        offensive_difference
        * 0.35
    )

    # -------------------------------------------------
    # 2. PITCHEO DEL EQUIPO
    # -------------------------------------------------

    home_era = safe_float(
        home_pitching.get(
            "era"
        ),
        4.50
    )

    away_era = safe_float(
        away_pitching.get(
            "era"
        ),
        4.50
    )

    pitching_difference = (
        away_era - home_era
    )

    home_score += (
        pitching_difference
        * 0.035
    )

    # -------------------------------------------------
    # 3. PITCHERS PROBABLES
    # -------------------------------------------------

    home_sp_era = safe_float(
        home_pitcher.get(
            "era"
        )
    )

    away_sp_era = safe_float(
        away_pitcher.get(
            "era"
        )
    )

    if (
        home_sp_era is not None
        and away_sp_era is not None
    ):

        home_score += (
            away_sp_era
            - home_sp_era
        ) * 0.025

    # -------------------------------------------------
    # 4. VENTAJA DE LOCAL
    # -------------------------------------------------

    home_score += 0.025

    # -------------------------------------------------
    # 5. FORMA RECIENTE
    # -------------------------------------------------

    home_win_form = (
        calculate_recent_form_score(
            home_form
        )
    )

    away_win_form = (
        calculate_recent_form_score(
            away_form
        )
    )

    form_difference = (
        home_win_form
        - away_win_form
    )

    home_score += (
        form_difference
        * 0.12
    )

    # -------------------------------------------------
    # 6. DIFERENCIAL DE CARRERAS
    # -------------------------------------------------

    home_run_form = (
        calculate_run_form_score(
            home_form
        )
    )

    away_run_form = (
        calculate_run_form_score(
            away_form
        )
    )

    run_form_difference = (
        home_run_form
        - away_run_form
    )

    run_component = (
        math.tanh(
            run_form_difference / 3.0
        )
        * 0.04
    )

    home_score += run_component

    # -------------------------------------------------
    # PROBABILIDAD FINAL
    # -------------------------------------------------

    probability = clamp(
        home_score
    )

    return {
        "home": round(
            probability,
            4
        ),
        "away": round(
            1 - probability,
            4
        ),
    }


# =========================================================
# ANÁLISIS PRINCIPAL
# =========================================================

def analyze_mlb_game(
    game_id
):
    """
    Analiza un partido MLB
    utilizando únicamente información
    disponible antes del comienzo.
    """

    # -------------------------------------------------
    # 1. OBTENER PARTIDO
    # -------------------------------------------------

    game = get_game(
        game_id
    )

    game_data = game.get(
        "gameData",
        {}
    )

    # -------------------------------------------------
    # 2. ESTADO
    # -------------------------------------------------

    status = (
        game_data
        .get(
            "status",
            {}
        )
        .get(
            "abstractGameState"
        )
    )

    detailed_status = (
        game_data
        .get(
            "status",
            {}
        )
        .get(
            "detailedState"
        )
    )

    # -------------------------------------------------
    # 3. EQUIPOS
    # -------------------------------------------------

    teams = game_data.get(
        "teams",
        {}
    )

    home_team = teams.get(
        "home",
        {}
    )

    away_team = teams.get(
        "away",
        {}
    )

    home_id = home_team.get(
        "id"
    )

    away_id = away_team.get(
        "id"
    )

    home_name = home_team.get(
        "name"
    )

    away_name = away_team.get(
        "name"
    )

    # -------------------------------------------------
    # 4. VENUE
    # -------------------------------------------------

    venue = (
        game_data
        .get(
            "venue",
            {}
        )
        .get(
            "name"
        )
    )

    # -------------------------------------------------
    # 5. FECHA
    # -------------------------------------------------

    datetime_value = (
        game_data
        .get(
            "datetime",
            {}
        )
        .get(
            "dateTime"
        )
    )

    # -------------------------------------------------
    # 6. PROTEGER CONTRA DATA LEAKAGE
    # -------------------------------------------------

    if status in {
        "Final",
        "Live"
    }:

        return {
            "success": False,

            "message": (
                "Este partido ya comenzó o terminó. "
                "El motor pregame no utilizará "
                "información posterior al inicio "
                "del partido."
            ),

            "game_id": str(
                game_id
            ),

            "status": status,

            "detailed_status":
                detailed_status,
        }

    # -------------------------------------------------
    # 7. ESTADÍSTICAS DE EQUIPOS
    # -------------------------------------------------

    home_stats = (
        get_team_season_stats(
            home_id
        )
    )

    away_stats = (
        get_team_season_stats(
            away_id
        )
    )

    # -------------------------------------------------
    # 8. PITCHERS PROBABLES
    # -------------------------------------------------

    probable_pitchers = (
        game_data
        .get(
            "probablePitchers",
            {}
        )
    )

    home_pitcher_info = (
        probable_pitchers
        .get(
            "home",
            {}
        )
    )

    away_pitcher_info = (
        probable_pitchers
        .get(
            "away",
            {}
        )
    )

    home_pitcher_id = (
        home_pitcher_info.get(
            "id"
        )
    )

    away_pitcher_id = (
        away_pitcher_info.get(
            "id"
        )
    )

    home_pitcher_stats = (
        get_player_pitching_stats(
            home_pitcher_id
        )
    )

    away_pitcher_stats = (
        get_player_pitching_stats(
            away_pitcher_id
        )
    )

    # -------------------------------------------------
    # 9. FORMA HISTÓRICA
    # -------------------------------------------------

    form_error = None

    try:

        matchup_form = (
            get_matchup_form(
                home_team_id=home_id,
                away_team_id=away_id,
                before_date=datetime_value,
            )
        )

        home_form = (
            matchup_form.get(
                "home",
                {}
            )
        )

        away_form = (
            matchup_form.get(
                "away",
                {}
            )
        )

    except Exception as exc:

        form_error = str(
            exc
        )

        home_form = {
            "last_5": {},
            "last_10": {},
            "last_15": {},
        }

        away_form = {
            "last_5": {},
            "last_10": {},
            "last_15": {},
        }

    # -------------------------------------------------
    # 10. PROBABILIDADES
    # -------------------------------------------------

    probabilities = (
        calculate_probability(
            home_stats["hitting"],
            away_stats["hitting"],
            home_stats["pitching"],
            away_stats["pitching"],
            home_pitcher_stats,
            away_pitcher_stats,
            home_form,
            away_form,
        )
    )

    # -------------------------------------------------
    # 11. FACTORES
    # -------------------------------------------------

    factors = {

        "home_advantage": 0.025,

        "home_team_ops":
            home_stats["hitting"].get(
                "ops"
            ),

        "away_team_ops":
            away_stats["hitting"].get(
                "ops"
            ),

        "home_team_era":
            home_stats["pitching"].get(
                "era"
            ),

        "away_team_era":
            away_stats["pitching"].get(
                "era"
            ),

        "home_pitcher_era":
            home_pitcher_stats.get(
                "era"
            ),

        "away_pitcher_era":
            away_pitcher_stats.get(
                "era"
            ),

        "recent_form": {
            "home": home_form,
            "away": away_form,
        },

        "recent_form_score": {
            "home":
                calculate_recent_form_score(
                    home_form
                ),

            "away":
                calculate_recent_form_score(
                    away_form
                ),
        },

        "recent_run_differential_per_game": {
            "home":
                calculate_run_form_score(
                    home_form
                ),

            "away":
                calculate_run_form_score(
                    away_form
                ),
        },
    }

    if form_error:

        factors[
            "form_engine_error"
        ] = form_error

    # -------------------------------------------------
    # 12. CONFIANZA
    # -------------------------------------------------

    probability_difference = abs(
        probabilities["home"]
        - probabilities["away"]
    )

    confidence = clamp(
        0.50
        + probability_difference
        * 0.75,
        0.50,
        0.90
    )

    # -------------------------------------------------
    # 13. GANADOR PROYECTADO
    # -------------------------------------------------

    predicted_team = (
        home_name
        if (
            probabilities["home"]
            >= probabilities["away"]
        )
        else away_name
    )

    # -------------------------------------------------
    # 14. CALIDAD DE DATOS
    # -------------------------------------------------

    home_form_games = (
        home_form
        .get(
            "last_15",
            {}
        )
        .get(
            "games",
            0
        )
    )

    away_form_games = (
        away_form
        .get(
            "last_15",
            {}
        )
        .get(
            "games",
            0
        )
    )

    if (
        home_form_games >= 15
        and away_form_games >= 15
    ):

        data_quality = 100

    elif (
        home_form_games >= 10
        and away_form_games >= 10
    ):

        data_quality = 90

    elif (
        home_form_games >= 5
        and away_form_games >= 5
    ):

        data_quality = 80

    else:

        data_quality = 65

    if form_error:

        data_quality = min(
            data_quality,
            70
        )

    # -------------------------------------------------
    # 15. RESPUESTA FINAL
    # -------------------------------------------------

    return {

        "success": True,

        "model_version":
            "1.2.0-form",

        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "game": {

            "game_id":
                str(game_id),

            "date":
                datetime_value,

            "status":
                status,

            "detailed_status":
                detailed_status,

            "venue":
                venue,

            "home":
                home_name,

            "away":
                away_name,

            "home_team_id":
                home_id,

            "away_team_id":
                away_id,
        },

        "prediction": {

            "winner":
                predicted_team,

            "home_probability":
                probabilities["home"],

            "away_probability":
                probabilities["away"],

            "confidence":
                round(
                    confidence,
                    4
                ),

            "data_quality":
                data_quality,
        },

        "factors":
            factors,
    }
