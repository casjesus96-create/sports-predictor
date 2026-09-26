import math
import requests
from datetime import datetime, timezone, timedelta

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
# CONFIGURACIÓN
# =========================================================

RECENT_GAMES_LIMIT = 30

RECENT_STRENGTH_WIN_RATE_WEIGHT = 0.45
RECENT_STRENGTH_RUN_DIFF_WEIGHT = 0.25
RECENT_STRENGTH_RUNS_SCORED_WEIGHT = 0.15
RECENT_STRENGTH_RUNS_ALLOWED_WEIGHT = 0.15


# =========================================================
# UTILIDADES
# =========================================================

def clamp(
    value,
    minimum=0.05,
    maximum=0.95,
):
    return max(
        minimum,
        min(maximum, value),
    )


def get_json(
    url,
    params=None,
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
    default=None,
):
    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return default


def safe_int(
    value,
    default=None,
):
    try:
        return int(value)
    except (
        TypeError,
        ValueError,
    ):
        return default


def stat_value(
    stats,
    *keys,
):
    stats = stats or {}

    for key in keys:
        value = stats.get(key)

        if value is not None:
            return value

    return None


# =========================================================
# PARTIDO MLB
# =========================================================

def get_game(
    game_id,
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
    season=2026,
):
    """
    Obtiene estadísticas de temporada
    de bateo y pitcheo.
    """

    if not team_id:
        return {
            "hitting": {},
            "pitching": {},
        }

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
# RECENT STRENGTH — ÚLTIMOS 30 PARTIDOS
# =========================================================

def _parse_game_date(
    value,
):
    """
    Convierte una fecha MLB en datetime UTC.
    """

    if not value:
        return None

    try:
        text = str(value)

        if text.endswith("Z"):
            text = text[:-1]

        parsed = datetime.fromisoformat(
            text,
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc,
            )

        return parsed.astimezone(
            timezone.utc,
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


def _format_api_date(
    value,
):
    """
    Devuelve YYYY-MM-DD.
    """

    if isinstance(
        value,
        datetime,
    ):
        return value.strftime(
            "%Y-%m-%d",
        )

    parsed = _parse_game_date(
        value,
    )

    if parsed:
        return parsed.strftime(
            "%Y-%m-%d",
        )

    return str(value)[:10]


def _get_recent_games_from_mlb(
    team_id,
    before_date=None,
    limit=RECENT_GAMES_LIMIT,
):
    """
    Obtiene directamente desde MLB Stats API
    los partidos anteriores del equipo.

    No utiliza mlb_game_history.
    No utiliza form_engine.
    No depende de scores almacenados localmente.

    La búsqueda retrocede por ventanas de 30 días
    hasta conseguir suficientes partidos.
    """

    if not team_id:
        return []

    try:
        team_id = int(team_id)
    except (
        TypeError,
        ValueError,
    ):
        return []

    limit = max(
        int(limit),
        1,
    )

    if before_date:
        cutoff = _parse_game_date(
            before_date,
        )
    else:
        cutoff = datetime.now(
            timezone.utc,
        )

    if cutoff is None:
        cutoff = datetime.now(
            timezone.utc,
        )

    # Dejamos un pequeño margen para garantizar
    # que no entre el propio partido analizado.
    cutoff_date = cutoff.date()

    collected = {}
    end_date = cutoff_date

    # Buscamos progresivamente hacia atrás.
    # 12 meses cubren sobradamente los 30 partidos.
    for _ in range(18):

        start_date = (
            end_date
            - timedelta(days=30)
        )

        params = {
            "sportId": 1,
            "teamId": team_id,
            "startDate": start_date.strftime(
                "%m/%d/%Y",
            ),
            "endDate": end_date.strftime(
                "%m/%d/%Y",
            ),
            "gameTypes": "R",
            "hydrate": (
                "team,linescore"
            ),
        }

        try:
            data = get_json(
                f"{MLB_API}/schedule",
                params,
            )

        except Exception:
            end_date = (
                start_date
                - timedelta(days=1)
            )
            continue

        for date_block in data.get(
            "dates",
            [],
        ):

            for game in date_block.get(
                "games",
                [],
            ):

                game_id = (
                    game.get(
                        "gamePk",
                    )
                )

                if not game_id:
                    continue

                status = (
                    game
                    .get(
                        "status",
                        {},
                    )
                    .get(
                        "abstractGameState",
                    )
                )

                if status != "Final":
                    continue

                game_datetime = (
                    game
                    .get(
                        "gameDate",
                    )
                )

                parsed_date = (
                    _parse_game_date(
                        game_datetime,
                    )
                )

                if not parsed_date:
                    continue

                # Protección contra data leakage.
                if parsed_date >= cutoff:
                    continue

                teams = (
                    game.get(
                        "teams",
                        {},
                    )
                )

                home = (
                    teams.get(
                        "home",
                        {},
                    )
                )

                away = (
                    teams.get(
                        "away",
                        {},
                    )
                )

                home_team = (
                    home.get(
                        "team",
                        {},
                    )
                )

                away_team = (
                    away.get(
                        "team",
                        {},
                    )
                )

                home_id = home_team.get(
                    "id",
                )

                away_id = away_team.get(
                    "id",
                )

                home_score = safe_int(
                    home.get(
                        "score",
                    )
                )

                away_score = safe_int(
                    away.get(
                        "score",
                    )
                )

                if (
                    home_score is None
                    or away_score is None
                ):
                    continue

                if (
                    str(team_id)
                    != str(home_id)
                    and
                    str(team_id)
                    != str(away_id)
                ):
                    continue

                collected[
                    str(game_id)
                ] = {
                    "game_id": str(
                        game_id,
                    ),
                    "game_date": (
                        parsed_date
                        .isoformat()
                    ),
                    "home_team_id": home_id,
                    "away_team_id": away_id,
                    "home_score": home_score,
                    "away_score": away_score,
                }

        if len(collected) >= limit:
            break

        end_date = (
            start_date
            - timedelta(days=1)
        )

    games = list(
        collected.values()
    )

    games.sort(
        key=lambda game: (
            _parse_game_date(
                game.get(
                    "game_date",
                )
            )
            or datetime.min.replace(
                tzinfo=timezone.utc,
            )
        ),
        reverse=True,
    )

    return games[:limit]


def calculate_recent_strength(
    team_id,
    before_date=None,
    limit=RECENT_GAMES_LIMIT,
):
    """
    Calcula la fuerza reciente del equipo
    utilizando hasta 30 partidos FINALIZADOS
    directamente desde MLB.

    Componentes:

    45% Win Rate
    25% Run Differential / Game
    15% Runs Scored / Game
    15% Runs Allowed / Game
    """

    games = _get_recent_games_from_mlb(
        team_id=team_id,
        before_date=before_date,
        limit=limit,
    )

    wins = 0
    losses = 0

    runs_scored = 0
    runs_allowed = 0

    valid_games = 0

    for game in games:

        home_id = game.get(
            "home_team_id",
        )

        away_id = game.get(
            "away_team_id",
        )

        home_score = safe_int(
            game.get(
                "home_score",
            )
        )

        away_score = safe_int(
            game.get(
                "away_score",
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

        elif str(team_id) == str(away_id):

            team_score = away_score
            opponent_score = home_score

        else:
            continue

        valid_games += 1

        runs_scored += team_score
        runs_allowed += opponent_score

        if team_score > opponent_score:
            wins += 1

        elif team_score < opponent_score:
            losses += 1

    if valid_games == 0:

        return {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "runs_scored": 0,
            "runs_allowed": 0,
            "run_differential": 0,
            "runs_scored_per_game": 0.0,
            "runs_allowed_per_game": 0.0,
            "run_differential_per_game": 0.0,
            "strength_score": 0.0,
            "quality": 0,
        }

    win_rate = (
        wins
        / valid_games
    )

    runs_scored_per_game = (
        runs_scored
        / valid_games
    )

    runs_allowed_per_game = (
        runs_allowed
        / valid_games
    )

    run_differential = (
        runs_scored
        - runs_allowed
    )

    run_differential_per_game = (
        run_differential
        / valid_games
    )

    # -------------------------------------------------
    # NORMALIZACIONES
    # -------------------------------------------------

    # Win rate:
    # 0.500 = 0
    # 1.000 = positivo
    # 0.000 = negativo
    win_component = (
        win_rate
        - 0.500
    )

    # Diferencial de carreras.
    # Limitamos la influencia de resultados extremos.
    run_diff_component = math.tanh(
        run_differential_per_game
        / 3.0
    )

    # Carreras anotadas.
    scoring_component = math.tanh(
        (
            runs_scored_per_game
            - 4.5
        )
        / 2.0
    )

    # Carreras permitidas.
    # Menos carreras permitidas = mejor.
    prevention_component = math.tanh(
        (
            4.5
            - runs_allowed_per_game
        )
        / 2.0
    )

    strength_score = (
        win_component
        * RECENT_STRENGTH_WIN_RATE_WEIGHT
        +
        run_diff_component
        * RECENT_STRENGTH_RUN_DIFF_WEIGHT
        +
        scoring_component
        * RECENT_STRENGTH_RUNS_SCORED_WEIGHT
        +
        prevention_component
        * RECENT_STRENGTH_RUNS_ALLOWED_WEIGHT
    )

    # Calidad basada en tamaño real de muestra.
    if valid_games >= 30:
        quality = 100

    elif valid_games >= 25:
        quality = 95

    elif valid_games >= 20:
        quality = 90

    elif valid_games >= 15:
        quality = 80

    elif valid_games >= 10:
        quality = 70

    else:
        quality = 60

    return {
        "games": valid_games,
        "wins": wins,
        "losses": losses,
        "win_rate": round(
            win_rate,
            4,
        ),
        "runs_scored": runs_scored,
        "runs_allowed": runs_allowed,
        "run_differential": run_differential,
        "runs_scored_per_game": round(
            runs_scored_per_game,
            3,
        ),
        "runs_allowed_per_game": round(
            runs_allowed_per_game,
            3,
        ),
        "run_differential_per_game": round(
            run_differential_per_game,
            3,
        ),
        "strength_score": round(
            strength_score,
            4,
        ),
        "quality": quality,
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
    home_recent_strength,
    away_recent_strength,
):
    """
    Modelo pregame 2.1.0.

    Componentes:

    1. OPS
    2. ERA de equipos
    3. ERA de pitchers probables
    4. Ventaja de local
    5. Recent Strength 30
    """

    home_score = 0.50

    # -------------------------------------------------
    # 1. OFENSIVA
    # -------------------------------------------------

    home_ops = safe_float(
        home_hitting.get(
            "ops",
        ),
        0.700,
    )

    away_ops = safe_float(
        away_hitting.get(
            "ops",
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
            "era",
        ),
        4.50,
    )

    away_era = safe_float(
        away_pitching.get(
            "era",
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
            "era",
        )
    )

    away_sp_era = safe_float(
        away_pitcher.get(
            "era",
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

    home_strength = safe_float(
        home_recent_strength.get(
            "strength_score",
        ),
        0.0,
    )

    away_strength = safe_float(
        away_recent_strength.get(
            "strength_score",
        ),
        0.0,
    )

    strength_difference = (
        home_strength
        - away_strength
    )

    home_score += (
        strength_difference
        * 0.18
    )

    # -------------------------------------------------
    # PROBABILIDAD FINAL
    # -------------------------------------------------

    probability = clamp(
        home_score,
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

def analyze_mlb_game(
    game_id,
):
    """
    Analiza un partido MLB utilizando
    exclusivamente información disponible
    antes del comienzo.
    """

    # -------------------------------------------------
    # 1. OBTENER PARTIDO
    # -------------------------------------------------

    game = get_game(
        game_id,
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
            "abstractGameState",
        )
    )

    detailed_status = (
        game_data
        .get(
            "status",
            {},
        )
        .get(
            "detailedState",
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
        "id",
    )

    away_id = away_team.get(
        "id",
    )

    home_name = home_team.get(
        "name",
    )

    away_name = away_team.get(
        "name",
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
            "name",
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
            "dateTime",
        )
    )

    # -------------------------------------------------
    # 6. PROTECCIÓN DATA LEAKAGE
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

            "game_id": str(
                game_id,
            ),

            "status": status,

            "detailed_status":
                detailed_status,
        }

    # -------------------------------------------------
    # 7. ESTADÍSTICAS DE TEMPORADA
    # -------------------------------------------------

    home_stats = (
        get_team_season_stats(
            home_id,
            season=2026,
        )
    )

    away_stats = (
        get_team_season_stats(
            away_id,
            season=2026,
        )
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
            "id",
        )
    )

    away_pitcher_id = (
        away_pitcher_info.get(
            "id",
        )
    )

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

    # -------------------------------------------------
    # 9. RECENT STRENGTH
    # -------------------------------------------------

    recent_strength_error = None

    try:

        home_recent_strength = (
            calculate_recent_strength(
                team_id=home_id,
                before_date=datetime_value,
                limit=30,
            )
        )

        away_recent_strength = (
            calculate_recent_strength(
                team_id=away_id,
                before_date=datetime_value,
                limit=30,
            )
        )

    except Exception as exc:

        recent_strength_error = str(
            exc
        )

        home_recent_strength = {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "runs_scored": 0,
            "runs_allowed": 0,
            "run_differential": 0,
            "runs_scored_per_game": 0.0,
            "runs_allowed_per_game": 0.0,
            "run_differential_per_game": 0.0,
            "strength_score": 0.0,
            "quality": 0,
        }

        away_recent_strength = {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "runs_scored": 0,
            "runs_allowed": 0,
            "run_differential": 0,
            "runs_scored_per_game": 0.0,
            "runs_allowed_per_game": 0.0,
            "run_differential_per_game": 0.0,
            "strength_score": 0.0,
            "quality": 0,
        }

    # -------------------------------------------------
    # 10. PROBABILIDADES
    # -------------------------------------------------

    probabilities = (
        calculate_probability(
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
            home_recent_strength,
            away_recent_strength,
        )
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
    # 12. DATOS OFENSIVOS / PITCHEO
    # -------------------------------------------------

    home_hitting = (
        home_stats.get(
            "hitting",
        )
        or {}
    )

    away_hitting = (
        away_stats.get(
            "hitting",
        )
        or {}
    )

    home_pitching = (
        home_stats.get(
            "pitching",
        )
        or {}
    )

    away_pitching = (
        away_stats.get(
            "pitching",
        )
        or {}
    )

    # -------------------------------------------------
    # 13. FACTORES
    # -------------------------------------------------

    factors = {

        "home_advantage": 0.025,

        "home_team_ops":
            home_hitting.get(
                "ops",
            ),

        "away_team_ops":
            away_hitting.get(
                "ops",
            ),

        "home_team_era":
            home_pitching.get(
                "era",
            ),

        "away_team_era":
            away_pitching.get(
                "era",
            ),

        "home_pitcher_era":
            home_pitcher_stats.get(
                "era",
            ),

        "away_pitcher_era":
            away_pitcher_stats.get(
                "era",
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
        # PITCHERS PROBABLES
        # -------------------------------------------------

        "probable_pitchers": {

            "home":
                home_pitcher_stats,

            "away":
                away_pitcher_stats,
        },

        # -------------------------------------------------
        # MATCHUP
        # -------------------------------------------------

        "matchup":
            matchup_data,

        # -------------------------------------------------
        # RECENT STRENGTH
        # -------------------------------------------------

        "recent_strength": {

            "window":
                30,

            "home":
                home_recent_strength,

            "away":
                away_recent_strength,

            "difference":
                round(
                    safe_float(
                        home_recent_strength.get(
                            "strength_score",
                        ),
                        0.0,
                    )
                    -
                    safe_float(
                        away_recent_strength.get(
                            "strength_score",
                        ),
                        0.0,
                    ),
                    4,
                ),
        },
    }

    if recent_strength_error:

        factors[
            "recent_strength_engine_error"
        ] = recent_strength_error

    if matchup_error:

        factors[
            "matchup_engine_error"
        ] = matchup_error

    # -------------------------------------------------
    # 14. CONFIANZA
    # -------------------------------------------------

    probability_difference = abs(
        probabilities["home"]
        -
        probabilities["away"]
    )

    confidence = clamp(
        0.50
        +
        probability_difference
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
            >=
            probabilities["away"]
        )
        else away_name
    )

    # -------------------------------------------------
    # 16. CALIDAD DE DATOS
    # -------------------------------------------------

    recent_quality_home = (
        safe_int(
            home_recent_strength.get(
                "quality",
            ),
            0,
        )
    )

    recent_quality_away = (
        safe_int(
            away_recent_strength.get(
                "quality",
            ),
            0,
        )
    )

    recent_quality = min(
        recent_quality_home,
        recent_quality_away,
    )

    # Calidad base de estadísticas de temporada.
    base_quality = 100

    # Si no tenemos pitcher probable,
    # reducimos la calidad.
    if not home_pitcher_stats:
        base_quality -= 5

    if not away_pitcher_stats:
        base_quality -= 5

    if recent_strength_error:
        base_quality = min(
            base_quality,
            60,
        )

    data_quality = round(
        (
            base_quality * 0.70
            +
            recent_quality * 0.30
        )
    )

    data_quality = max(
        0,
        min(
            100,
            data_quality,
        ),
    )

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
                timezone.utc,
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
