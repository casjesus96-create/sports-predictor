import math
import requests
from datetime import datetime, timezone

from form_engine import get_matchup_form
from matchup_engine import get_matchup_data
from bullpen_engine import get_bullpen_matchup_data


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
    Obtiene por separado las estadísticas de temporada de bateo
    y pitcheo del equipo. Separar las consultas evita perder uno
    de los grupos cuando MLB Stats API no devuelve correctamente
    la respuesta combinada.
    """

    team_id = int(team_id)
    season = int(season)

    result = {
        "hitting": {},
        "pitching": {},
    }

    for group in ("hitting", "pitching"):
        url = f"{MLB_API}/teams/{team_id}/stats"

        params = {
            "stats": "season",
            "group": group,
            "season": season,
        }

        data = get_json(
            url,
            params
        )

        for stat_group in data.get("stats") or []:
            splits = stat_group.get("splits") or []

            if not splits:
                continue

            stats = splits[0].get("stat") or {}

            if stats:
                result[group] = stats
                break

    return result


# =========================================================
# ESTADÍSTICAS DEL PITCHER
# =========================================================

def get_player_pitching_stats(
    player_id,
    season=2026
):
    """
    Obtiene estadísticas de temporada del pitcher probable.
    """

    if not player_id:
        return {}

    player_id = int(player_id)
    season = int(season)

    url = f"{MLB_API}/people/{player_id}/stats"

    params = {
        "stats": "season",
        "group": "pitching",
        "season": season,
    }

    data = get_json(
        url,
        params
    )

    for stat_group in data.get("stats") or []:
        splits = stat_group.get("splits") or []

        if splits:
            return splits[0].get("stat") or {}

    return {}


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

    # -------------------------------------------------
    # 11B. MATCHUP 2.0
    # -------------------------------------------------

    matchup_data = {}
    matchup_error = None

    try:

        matchup_data = get_matchup_data(
            game_id=game_id,
            home_team_id=home_id,
            away_team_id=away_id,
            before_date=datetime_value,
            season=2026,
            game_type="R",
        ) or {}

    except Exception as exc:

        matchup_error = str(
            exc
        )

        matchup_data = {}

    # El matchup_engine es la fuente canónica de pitchers y manos.
    # No dependemos únicamente de gameData.probablePitchers del feed.

    matchup_pitchers = (
        matchup_data.get(
            "pitchers"
        )
        or {}
    )

    matchup_home_pitcher = (
        matchup_pitchers.get(
            "home"
        )
        or {}
    )

    matchup_away_pitcher = (
        matchup_pitchers.get(
            "away"
        )
        or {}
    )

    if matchup_home_pitcher:

        home_pitcher_id = (
            matchup_home_pitcher.get(
                "pitcher_id"
            )
            or matchup_home_pitcher.get(
                "id"
            )
        )

        home_pitcher_name = (
            matchup_home_pitcher.get(
                "pitcher_name"
            )
            or matchup_home_pitcher.get(
                "name"
            )
        )

    else:

        home_pitcher_name = None

    if matchup_away_pitcher:

        away_pitcher_id = (
            matchup_away_pitcher.get(
                "pitcher_id"
            )
            or matchup_away_pitcher.get(
                "id"
            )
        )

        away_pitcher_name = (
            matchup_away_pitcher.get(
                "pitcher_name"
            )
            or matchup_away_pitcher.get(
                "name"
            )
        )

    else:

        away_pitcher_name = None

    # Si matchup_engine no encontró pitcher,
    # conservamos el fallback del feed original.

    if not home_pitcher_id:

        home_pitcher_id = (
            home_pitcher_info.get(
                "id"
            )
        )

    if not away_pitcher_id:

        away_pitcher_id = (
            away_pitcher_info.get(
                "id"
            )
        )

    if home_pitcher_name is None:

        home_pitcher_name = (
            home_pitcher_info.get(
                "fullName"
            )
            or home_pitcher_info.get(
                "name"
            )
        )

    if away_pitcher_name is None:

        away_pitcher_name = (
            away_pitcher_info.get(
                "fullName"
            )
            or away_pitcher_info.get(
                "name"
            )
        )

    # Volvemos a obtener las estadísticas ahora que conocemos
    # los IDs canónicos de los pitchers del matchup.

    home_pitcher_stats = (
        get_player_pitching_stats(
            home_pitcher_id,
            season=2026,
        )
    )

    away_pitcher_stats = (
        get_player_pitching_stats(
            away_pitcher_id,
            season=2026,
        )
    )

    home_hitting = (
        home_stats.get(
            "hitting"
        )
        or {}
    )

    away_hitting = (
        away_stats.get(
            "hitting"
        )
        or {}
    )

    home_pitching = (
        home_stats.get(
            "pitching"
        )
        or {}
    )

    away_pitching = (
        away_stats.get(
            "pitching"
        )
        or {}
    )

    def stat_value(
        stats,
        *keys
    ):

        for key in keys:

            if stats.get(key) is not None:

                return stats.get(key)

        return None

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

        # =================================================
        # ESTADÍSTICAS OFENSIVAS DE TEMPORADA
        # =================================================

        "offense": {

            "home": {

                "hits":
                    stat_value(
                        home_hitting,
                        "hits"
                    ),

                "home_runs":
                    stat_value(
                        home_hitting,
                        "homeRuns",
                        "home_runs"
                    ),

                "strikeouts":
                    stat_value(
                        home_hitting,
                        "strikeOuts",
                        "strikeouts"
                    ),

                "runs":
                    stat_value(
                        home_hitting,
                        "runs"
                    ),

                "walks":
                    stat_value(
                        home_hitting,
                        "baseOnBalls",
                        "walks"
                    ),

                "avg":
                    stat_value(
                        home_hitting,
                        "avg"
                    ),

                "obp":
                    stat_value(
                        home_hitting,
                        "obp"
                    ),

                "slg":
                    stat_value(
                        home_hitting,
                        "slg"
                    ),

                "ops":
                    stat_value(
                        home_hitting,
                        "ops"
                    ),
            },

            "away": {

                "hits":
                    stat_value(
                        away_hitting,
                        "hits"
                    ),

                "home_runs":
                    stat_value(
                        away_hitting,
                        "homeRuns",
                        "home_runs"
                    ),

                "strikeouts":
                    stat_value(
                        away_hitting,
                        "strikeOuts",
                        "strikeouts"
                    ),

                "runs":
                    stat_value(
                        away_hitting,
                        "runs"
                    ),

                "walks":
                    stat_value(
                        away_hitting,
                        "baseOnBalls",
                        "walks"
                    ),

                "avg":
                    stat_value(
                        away_hitting,
                        "avg"
                    ),

                "obp":
                    stat_value(
                        away_hitting,
                        "obp"
                    ),

                "slg":
                    stat_value(
                        away_hitting,
                        "slg"
                    ),

                "ops":
                    stat_value(
                        away_hitting,
                        "ops"
                    ),
            },
        },

        # =================================================
        # ESTADÍSTICAS DE PITCHEO DE TEMPORADA
        # =================================================

        "pitching": {

            "home": {

                "era":
                    stat_value(
                        home_pitching,
                        "era"
                    ),

                "whip":
                    stat_value(
                        home_pitching,
                        "whip"
                    ),

                "strikeouts":
                    stat_value(
                        home_pitching,
                        "strikeOuts",
                        "strikeouts"
                    ),

                "hits_allowed":
                    stat_value(
                        home_pitching,
                        "hits"
                    ),

                "home_runs_allowed":
                    stat_value(
                        home_pitching,
                        "homeRuns",
                        "home_runs"
                    ),

                "walks":
                    stat_value(
                        home_pitching,
                        "baseOnBalls",
                        "walks"
                    ),
            },

            "away": {

                "era":
                    stat_value(
                        away_pitching,
                        "era"
                    ),

                "whip":
                    stat_value(
                        away_pitching,
                        "whip"
                    ),

                "strikeouts":
                    stat_value(
                        away_pitching,
                        "strikeOuts",
                        "strikeouts"
                    ),

                "hits_allowed":
                    stat_value(
                        away_pitching,
                        "hits"
                    ),

                "home_runs_allowed":
                    stat_value(
                        away_pitching,
                        "homeRuns",
                        "home_runs"
                    ),

                "walks":
                    stat_value(
                        away_pitching,
                        "baseOnBalls",
                        "walks"
                    ),
            },
        },

        # =================================================
        # PITCHERS PROBABLES
        # =================================================

        "probable_pitchers": {

            "home": {

                **(
                    matchup_home_pitcher
                    or {}
                ),

                "pitcher_id":
                    home_pitcher_id,

                "id":
                    home_pitcher_id,

                "pitcher_name":
                    home_pitcher_name,

                "name":
                    home_pitcher_name,

                "pitcher_hand": (
                    matchup_home_pitcher.get(
                        "pitcher_hand"
                    )
                    if matchup_home_pitcher
                    else None
                ),

                "stats":
                    home_pitcher_stats,
            },

            "away": {

                **(
                    matchup_away_pitcher
                    or {}
                ),

                "pitcher_id":
                    away_pitcher_id,

                "id":
                    away_pitcher_id,

                "pitcher_name":
                    away_pitcher_name,

                "name":
                    away_pitcher_name,

                "pitcher_hand": (
                    matchup_away_pitcher.get(
                        "pitcher_hand"
                    )
                    if matchup_away_pitcher
                    else None
                ),

                "stats":
                    away_pitcher_stats,
            },
        },

        # =================================================
        # MATCHUP
        # =================================================

        "matchup":
            matchup_data,

        # =================================================
        # ESTADÍSTICAS DE TEMPORADA
        # =================================================

        "team_season_stats": {

            "home": {

                "hitting":
                    home_hitting,

                "pitching":
                    home_pitching,
            },

            "away": {

                "hitting":
                    away_hitting,

                "pitching":
                    away_pitching,
            },
        },

        # =================================================
        # FORMA RECIENTE
        # =================================================

        "recent_form": {

            "home":
                home_form,

            "away":
                away_form,
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

    if matchup_error:

        factors[
            "matchup_engine_error"
        ] = matchup_error

    # -------------------------------------------------
    # 11C. BULLPEN
    # -------------------------------------------------
    #
    # El bullpen se calcula como un factor informativo
    # independiente.
    #
    # IMPORTANTE:
    #
    # En esta etapa NO modifica todavía las probabilidades
    # del modelo.
    #
    # Primero almacenamos y validamos la señal con datos
    # reales antes de darle peso predictivo.
    #
    # Esto evita crear una segunda lógica de proyección
    # o alterar el modelo MLB 2.0.0-matchup sin calibración.
    # -------------------------------------------------

    bullpen_error = None

    bullpen_data = {}

    try:

        bullpen_data = (
            get_bullpen_matchup_data(
                home_team_id=home_id,
                away_team_id=away_id,
                before_datetime=datetime_value,
                season=2026,
            )
            or {}
        )

    except Exception as exc:

        bullpen_error = str(
            exc
        )

        bullpen_data = {

            "available": False,

            "home": {

                "team_id":
                    home_id,

                "availability_score":
                    None,

                "confidence":
                    0.0,
            },

            "away": {

                "team_id":
                    away_id,

                "availability_score":
                    None,

                "confidence":
                    0.0,
            },

            "difference":
                0.0,

            "signal":
                0.0,

            "confidence":
                0.0,

            "error":
                bullpen_error,
        }

    # -------------------------------------------------
    # GUARDAR BULLPEN DENTRO DE FACTORS
    # -------------------------------------------------

    factors[
        "bullpen"
    ] = bullpen_data

    if bullpen_error:

        factors[
            "bullpen_engine_error"
        ] = bullpen_error

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
            "2.0.0-matchup",

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
