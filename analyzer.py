import math
import requests
from datetime import datetime, timezone

from matchup_engine import get_matchup_data


# =========================================================
# MLB API
# =========================================================

MLB_API = "https://statsapi.mlb.com/api/v1"
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1"

MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0",
    "Accept": "application/json",
}


# =========================================================
# UTILIDADES
# =========================================================

def clamp(value, minimum=0.05, maximum=0.95):
    return max(
        minimum,
        min(maximum, value)
    )


def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers=MLB_HEADERS,
    )

    response.raise_for_status()

    return response.json()


def safe_float(value, default=None):
    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return default


def safe_int(value, default=None):
    try:
        return int(value)
    except (
        TypeError,
        ValueError,
    ):
        return default


# =========================================================
# PARTIDO MLB
# =========================================================

def get_game(game_id):
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

def get_team_season_stats(team_id, season=2026):
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
        params,
    )

    result = {
        "hitting": {},
        "pitching": {},
    }

    for split in data.get(
        "stats",
        [],
    ):

        group = (
            split
            .get(
                "group",
                {},
            )
            .get(
                "displayName",
                "",
            )
            .lower()
        )

        splits = split.get(
            "splits",
            [],
        )

        if not splits:
            continue

        stats = splits[0].get(
            "stat",
            {},
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
    season=2026,
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
        params,
    )

    stats_blocks = data.get(
        "stats",
        [],
    )

    if not stats_blocks:
        return {}

    splits = (
        stats_blocks[0]
        .get(
            "splits",
            [],
        )
    )

    if not splits:
        return {}

    return splits[0].get(
        "stat",
        {},
    )


# =========================================================
# RECENT STRENGTH 30
# =========================================================

def get_recent_games(
    team_id,
    before_date=None,
    limit=30,
):
    """
    Obtiene los últimos partidos FINALIZADOS del equipo
    directamente desde MLB Stats API.

    Esta función reemplaza la dependencia del form_engine
    para evitar que las ventanas last_5/10/15 aparezcan
    como 0-0 cuando la fuente histórica no está completa.

    La muestra principal utiliza hasta 30 partidos.
    """

    if not team_id:
        return []

    url = f"{MLB_API}/schedule"

    params = {
        "sportId": 1,
        "teamId": team_id,
        "hydrate": "team",
        "gameType": "R",
        "fields": (
            "dates,"
            "dates.date,"
            "dates.games,"
            "dates.games.gamePk,"
            "dates.games.gameDate,"
            "dates.games.status,"
            "dates.games.teams,"
            "dates.games.teams.home,"
            "dates.games.teams.home.team,"
            "dates.games.teams.home.score,"
            "dates.games.teams.away,"
            "dates.games.teams.away.team,"
            "dates.games.teams.away.score"
        ),
    }

    try:

        data = get_json(
            url,
            params,
        )

    except Exception:
        return []

    games = []

    before_dt = None

    if before_date:

        try:
            before_dt = datetime.fromisoformat(
                str(before_date).replace(
                    "Z",
                    "+00:00",
                )
            )

            if before_dt.tzinfo is None:
                before_dt = before_dt.replace(
                    tzinfo=timezone.utc
                )

        except (
            TypeError,
            ValueError,
        ):
            before_dt = None

    for date_block in data.get(
        "dates",
        [],
    ):

        for game in date_block.get(
            "games",
            [],
        ):

            status = (
                game
                .get(
                    "status",
                    {},
                )
                .get(
                    "abstractGameState"
                )
            )

            if status != "Final":
                continue

            game_date = game.get(
                "gameDate"
            )

            if before_dt and game_date:

                try:
                    game_dt = datetime.fromisoformat(
                        str(game_date).replace(
                            "Z",
                            "+00:00",
                        )
                    )

                    if game_dt >= before_dt:
                        continue

                except (
                    TypeError,
                    ValueError,
                ):
                    pass

            teams = game.get(
                "teams",
                {},
            )

            home = teams.get(
                "home",
                {},
            )

            away = teams.get(
                "away",
                {},
            )

            home_team = home.get(
                "team",
                {},
            )

            away_team = away.get(
                "team",
                {},
            )

            home_id = home_team.get(
                "id"
            )

            away_id = away_team.get(
                "id"
            )

            home_score = safe_int(
                home.get(
                    "score"
                )
            )

            away_score = safe_int(
                away.get(
                    "score"
                )
            )

            if (
                home_id is None
                or away_id is None
                or home_score is None
                or away_score is None
            ):
                continue

            if (
                str(team_id) != str(home_id)
                and str(team_id) != str(away_id)
            ):
                continue

            games.append(
                {
                    "game_id":
                        game.get(
                            "gamePk"
                        ),

                    "game_date":
                        game_date,

                    "home_team_id":
                        home_id,

                    "away_team_id":
                        away_id,

                    "home_score":
                        home_score,

                    "away_score":
                        away_score,
                }
            )

    games.sort(
        key=lambda x: (
            x.get(
                "game_date"
            )
            or ""
        ),
        reverse=True,
    )

    return games[:limit]


def calculate_recent_strength(
    team_id,
    before_date=None,
    limit=30,
):
    """
    Calcula una señal de fuerza reciente utilizando
    hasta los últimos 30 partidos oficiales.

    Componentes:

    1. Win rate
    2. Diferencial de carreras por partido
    3. Carreras anotadas por partido
    4. Carreras permitidas por partido

    Pesos:

    Win rate                  = 45%
    Run differential          = 25%
    Runs scored               = 15%
    Runs allowed              = 15%

    Devuelve también los datos completos utilizados
    para que el frontend pueda mostrarlos.
    """

    games = get_recent_games(
        team_id=team_id,
        before_date=before_date,
        limit=limit,
    )

    if not games:
        return {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.5,
            "runs_scored": 0,
            "runs_allowed": 0,
            "run_differential": 0,
            "runs_scored_per_game": 0,
            "runs_allowed_per_game": 0,
            "run_differential_per_game": 0,
            "strength_score": 0.5,
        }

    wins = 0
    losses = 0
    runs_scored = 0
    runs_allowed = 0

    home_games = 0
    home_wins = 0

    away_games = 0
    away_wins = 0

    for game in games:

        home_id = game.get(
            "home_team_id"
        )

        away_id = game.get(
            "away_team_id"
        )

        home_score = safe_int(
            game.get(
                "home_score"
            )
        )

        away_score = safe_int(
            game.get(
                "away_score"
            )
        )

        if (
            home_score is None
            or away_score is None
        ):
            continue

        if str(team_id) == str(home_id):

            team_score = home_score
            opponent_score = away_score

            home_games += 1

            if team_score > opponent_score:
                wins += 1
                home_wins += 1

            elif team_score < opponent_score:
                losses += 1

        elif str(team_id) == str(away_id):

            team_score = away_score
            opponent_score = home_score

            away_games += 1

            if team_score > opponent_score:
                wins += 1
                away_wins += 1

            elif team_score < opponent_score:
                losses += 1

        else:
            continue

        runs_scored += team_score
        runs_allowed += opponent_score

    valid_games = wins + losses

    if valid_games <= 0:

        return {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.5,
            "runs_scored": 0,
            "runs_allowed": 0,
            "run_differential": 0,
            "runs_scored_per_game": 0,
            "runs_allowed_per_game": 0,
            "run_differential_per_game": 0,
            "strength_score": 0.5,
        }

    win_rate = (
        wins / valid_games
    )

    runs_scored_per_game = (
        runs_scored / valid_games
    )

    runs_allowed_per_game = (
        runs_allowed / valid_games
    )

    run_differential = (
        runs_scored
        - runs_allowed
    )

    run_differential_per_game = (
        run_differential
        / valid_games
    )

    # Normalizamos los componentes para evitar
    # que las carreras dominen la probabilidad.

    win_component = clamp(
        win_rate,
        0.0,
        1.0,
    )

    run_diff_component = (
        0.5
        + math.tanh(
            run_differential_per_game
            / 3.0
        )
        * 0.5
    )

    scoring_component = (
        0.5
        + math.tanh(
            (
                runs_scored_per_game
                - 4.5
            )
            / 2.5
        )
        * 0.5
    )

    prevention_component = (
        0.5
        + math.tanh(
            (
                4.5
                - runs_allowed_per_game
            )
            / 2.5
        )
        * 0.5
    )

    strength_score = (
        win_component * 0.45
        + run_diff_component * 0.25
        + scoring_component * 0.15
        + prevention_component * 0.15
    )

    return {
        "games":
            valid_games,

        "wins":
            wins,

        "losses":
            losses,

        "win_rate":
            round(
                win_rate,
                4,
            ),

        "runs_scored":
            runs_scored,

        "runs_allowed":
            runs_allowed,

        "run_differential":
            run_differential,

        "runs_scored_per_game":
            round(
                runs_scored_per_game,
                3,
            ),

        "runs_allowed_per_game":
            round(
                runs_allowed_per_game,
                3,
            ),

        "run_differential_per_game":
            round(
                run_differential_per_game,
                3,
            ),

        "home_games":
            home_games,

        "home_wins":
            home_wins,

        "away_games":
            away_games,

        "away_wins":
            away_wins,

        "strength_score":
            round(
                strength_score,
                4,
            ),
    }


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
    home_strength,
    away_strength,
):
    """
    Modelo pregame 2.1.

    Componentes:

    1. OPS de temporada
    2. ERA de equipos
    3. ERA de pitchers probables
    4. Ventaja de local
    5. Recent Strength 30

    Recent Strength utiliza una muestra de hasta
    30 partidos anteriores al encuentro.
    """

    home_score = 0.50

    # -------------------------------------------------
    # 1. OFENSIVA
    # -------------------------------------------------

    home_ops = safe_float(
        home_hitting.get(
            "ops"
        ),
        0.700,
    )

    away_ops = safe_float(
        away_hitting.get(
            "ops"
        ),
        0.700,
    )

    offensive_difference = (
        home_ops
        - away_ops
    )

    home_score += (
        offensive_difference
        * 0.35
    )

    # -------------------------------------------------
    # 2. PITCHEO DE EQUIPO
    # -------------------------------------------------

    home_era = safe_float(
        home_pitching.get(
            "era"
        ),
        4.50,
    )

    away_era = safe_float(
        away_pitching.get(
            "era"
        ),
        4.50,
    )

    pitching_difference = (
        away_era
        - home_era
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
    # 5. RECENT STRENGTH 30
    # -------------------------------------------------

    home_strength_score = safe_float(
        home_strength.get(
            "strength_score"
        ),
        0.5,
    )

    away_strength_score = safe_float(
        away_strength.get(
            "strength_score"
        ),
        0.5,
    )

    strength_difference = (
        home_strength_score
        - away_strength_score
    )

    home_score += (
        strength_difference
        * 0.30
    )

    # -------------------------------------------------
    # PROBABILIDAD FINAL
    # -------------------------------------------------

    probability = clamp(
        home_score
    )

    return {
        "home": round(
            probability,
            4,
        ),

        "away": round(
            1 - probability,
            4,
        ),
    }


# =========================================================
# ANÁLISIS PRINCIPAL
# =========================================================

def analyze_mlb_game(game_id):
    """
    Analiza un partido MLB utilizando exclusivamente
    información disponible antes del comienzo.

    Modelo:
        2.1.0-recent-strength-30
    """

    # -------------------------------------------------
    # 1. OBTENER PARTIDO
    # -------------------------------------------------

    game = get_game(
        game_id
    )

    game_data = game.get(
        "gameData",
        {},
    )

    # -------------------------------------------------
    # 2. ESTADO
    # -------------------------------------------------

    status = (
        game_data
        .get(
            "status",
            {},
        )
        .get(
            "abstractGameState"
        )
    )

    detailed_status = (
        game_data
        .get(
            "status",
            {},
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
        {},
    )

    home_team = teams.get(
        "home",
        {},
    )

    away_team = teams.get(
        "away",
        {},
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
            {},
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
            {},
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
        "Live",
    }:

        return {
            "success": False,

            "message": (
                "Este partido ya comenzó o terminó. "
                "El motor pregame no utilizará "
                "información posterior al inicio "
                "del partido."
            ),

            "game_id":
                str(game_id),

            "status":
                status,

            "detailed_status":
                detailed_status,
        }

    # -------------------------------------------------
    # 7. ESTADÍSTICAS DE EQUIPOS
    # -------------------------------------------------

    home_stats = get_team_season_stats(
        home_id
    )

    away_stats = get_team_season_stats(
        away_id
    )

    # -------------------------------------------------
    # 8. PITCHERS PROBABLES
    # -------------------------------------------------

    probable_pitchers = (
        game_data
        .get(
            "probablePitchers",
            {},
        )
    )

    home_pitcher_info = (
        probable_pitchers
        .get(
            "home",
            {},
        )
    )

    away_pitcher_info = (
        probable_pitchers
        .get(
            "away",
            {},
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
    # 9. RECENT STRENGTH 30
    # -------------------------------------------------

    home_strength_error = None
    away_strength_error = None

    try:

        home_strength = (
            calculate_recent_strength(
                home_id,
                before_date=datetime_value,
                limit=30,
            )
        )

    except Exception as exc:

        home_strength_error = str(
            exc
        )

        home_strength = {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.5,
            "runs_scored": 0,
            "runs_allowed": 0,
            "run_differential": 0,
            "runs_scored_per_game": 0,
            "runs_allowed_per_game": 0,
            "run_differential_per_game": 0,
            "strength_score": 0.5,
        }

    try:

        away_strength = (
            calculate_recent_strength(
                away_id,
                before_date=datetime_value,
                limit=30,
            )
        )

    except Exception as exc:

        away_strength_error = str(
            exc
        )

        away_strength = {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.5,
            "runs_scored": 0,
            "runs_allowed": 0,
            "run_differential": 0,
            "runs_scored_per_game": 0,
            "runs_allowed_per_game": 0,
            "run_differential_per_game": 0,
            "strength_score": 0.5,
        }

    # -------------------------------------------------
    # 10. PROBABILIDADES
    # -------------------------------------------------

    probabilities = calculate_probability(
        home_stats.get(
            "hitting",
            {},
        ),
        away_stats.get(
            "hitting",
            {},
        ),
        home_stats.get(
            "pitching",
            {},
        ),
        away_stats.get(
            "pitching",
            {},
        ),
        home_pitcher_stats,
        away_pitcher_stats,
        home_strength,
        away_strength,
    )

    # -------------------------------------------------
    # 11. MATCHUP 2.0
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

    # -------------------------------------------------
    # 12. ESTADÍSTICAS
    # -------------------------------------------------

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

    def stat_value(stats, *keys):

        for key in keys:

            if stats.get(key) is not None:
                return stats.get(key)

        return None

    # -------------------------------------------------
    # 13. FACTORES
    # -------------------------------------------------

    factors = {

        "home_advantage":
            0.025,

        "home_team_ops":
            home_hitting.get(
                "ops"
            ),

        "away_team_ops":
            away_hitting.get(
                "ops"
            ),

        "home_team_era":
            home_pitching.get(
                "era"
            ),

        "away_team_era":
            away_pitching.get(
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

        # -------------------------------------------------
        # OFENSIVA
        # -------------------------------------------------

        "offense": {

            "home": {

                "hits":
                    stat_value(
                        home_hitting,
                        "hits",
                    ),

                "home_runs":
                    stat_value(
                        home_hitting,
                        "homeRuns",
                        "home_runs",
                    ),

                "strikeouts":
                    stat_value(
                        home_hitting,
                        "strikeOuts",
                        "strikeouts",
                    ),

                "runs":
                    stat_value(
                        home_hitting,
                        "runs",
                    ),

                "walks":
                    stat_value(
                        home_hitting,
                        "baseOnBalls",
                        "walks",
                    ),

                "avg":
                    stat_value(
                        home_hitting,
                        "avg",
                    ),

                "obp":
                    stat_value(
                        home_hitting,
                        "obp",
                    ),

                "slg":
                    stat_value(
                        home_hitting,
                        "slg",
                    ),

                "ops":
                    stat_value(
                        home_hitting,
                        "ops",
                    ),
            },

            "away": {

                "hits":
                    stat_value(
                        away_hitting,
                        "hits",
                    ),

                "home_runs":
                    stat_value(
                        away_hitting,
                        "homeRuns",
                        "home_runs",
                    ),

                "strikeouts":
                    stat_value(
                        away_hitting,
                        "strikeOuts",
                        "strikeouts",
                    ),

                "runs":
                    stat_value(
                        away_hitting,
                        "runs",
                    ),

                "walks":
                    stat_value(
                        away_hitting,
                        "baseOnBalls",
                        "walks",
                    ),

                "avg":
                    stat_value(
                        away_hitting,
                        "avg",
                    ),

                "obp":
                    stat_value(
                        away_hitting,
                        "obp",
                    ),

                "slg":
                    stat_value(
                        away_hitting,
                        "slg",
                    ),

                "ops":
                    stat_value(
                        away_hitting,
                        "ops",
                    ),
            },
        },

        # -------------------------------------------------
        # PITCHEO
        # -------------------------------------------------

        "pitching": {

            "home": {

                "era":
                    stat_value(
                        home_pitching,
                        "era",
                    ),

                "whip":
                    stat_value(
                        home_pitching,
                        "whip",
                    ),

                "strikeouts":
                    stat_value(
                        home_pitching,
                        "strikeOuts",
                        "strikeouts",
                    ),

                "hits_allowed":
                    stat_value(
                        home_pitching,
                        "hits",
                    ),

                "home_runs_allowed":
                    stat_value(
                        home_pitching,
                        "homeRuns",
                        "home_runs",
                    ),

                "walks":
                    stat_value(
                        home_pitching,
                        "baseOnBalls",
                        "walks",
                    ),
            },

            "away": {

                "era":
                    stat_value(
                        away_pitching,
                        "era",
                    ),

                "whip":
                    stat_value(
                        away_pitching,
                        "whip",
                    ),

                "strikeouts":
                    stat_value(
                        away_pitching,
                        "strikeOuts",
                        "strikeouts",
                    ),

                "hits_allowed":
                    stat_value(
                        away_pitching,
                        "hits",
                    ),

                "home_runs_allowed":
                    stat_value(
                        away_pitching,
                        "homeRuns",
                        "home_runs",
                    ),

                "walks":
                    stat_value(
                        away_pitching,
                        "baseOnBalls",
                        "walks",
                    ),
            },
        },

        # -------------------------------------------------
        # PITCHERS
        # -------------------------------------------------

        "probable_pitchers": {

            "home":
                home_pitcher_stats,

            "away":
                away_pitcher_stats,
        },

        # -------------------------------------------------
        # RECENT STRENGTH 30
        # -------------------------------------------------

        "recent_strength": {

            "window":
                30,

            "home":
                home_strength,

            "away":
                away_strength,
        },

        # -------------------------------------------------
        # MATCHUP
        # -------------------------------------------------

        "matchup":
            matchup_data,
    }

    if home_strength_error:

        factors[
            "home_recent_strength_error"
        ] = home_strength_error

    if away_strength_error:

        factors[
            "away_recent_strength_error"
        ] = away_strength_error

    if matchup_error:

        factors[
            "matchup_engine_error"
        ] = matchup_error

    # -------------------------------------------------
    # 14. CONFIANZA
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
        0.90,
    )

    # -------------------------------------------------
    # 15. GANADOR
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
    # 16. CALIDAD DE DATOS
    # -------------------------------------------------

    home_games = safe_int(
        home_strength.get(
            "games"
        ),
        0,
    )

    away_games = safe_int(
        away_strength.get(
            "games"
        ),
        0,
    )

    minimum_recent_games = min(
        home_games,
        away_games,
    )

    if minimum_recent_games >= 30:

        data_quality = 100

    elif minimum_recent_games >= 25:

        data_quality = 95

    elif minimum_recent_games >= 20:

        data_quality = 90

    elif minimum_recent_games >= 15:

        data_quality = 85

    elif minimum_recent_games >= 10:

        data_quality = 75

    elif minimum_recent_games >= 5:

        data_quality = 65

    else:

        data_quality = 50

    # -------------------------------------------------
    # 17. RESPUESTA FINAL
    # -------------------------------------------------

    return {

        "success":
            True,

        "model_version":
            "2.1.0-recent-strength-30",

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
                    4,
                ),

            "data_quality":
                data_quality,
        },

        "factors":
            factors,
    }
