from datetime import datetime, timezone

from repository import get_supabase_client


# =========================================================
# H2H - HEAD TO HEAD
# =========================================================

def get_h2h_games(
    home_team_id,
    away_team_id,
    before_date=None,
    limit=10,
):
    """
    Obtiene los últimos enfrentamientos directos entre
    dos equipos antes de una fecha determinada.

    Se utiliza protección contra leakage:
    ningún partido posterior o igual a before_date
    puede entrar en el cálculo.
    """

    supabase = get_supabase_client()

    query = (
        supabase
        .table("mlb_game_history")
        .select("*")
        .eq("status", "Final")
        .or_(
            (
                f"and("
                f"home_team_id.eq.{home_team_id},"
                f"away_team_id.eq.{away_team_id}"
                f"),"
                f"and("
                f"home_team_id.eq.{away_team_id},"
                f"away_team_id.eq.{home_team_id}"
                f")"
            )
        )
        .order(
            "game_date",
            desc=True
        )
        .limit(limit)
    )

    if before_date:
        query = query.lt(
            "game_date",
            before_date
        )

    response = query.execute()

    return response.data or []


def calculate_h2h(
    home_team_id,
    away_team_id,
    before_date=None,
    limit=10,
):
    """
    Calcula estadísticas H2H entre dos equipos.
    """

    games = get_h2h_games(
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        before_date=before_date,
        limit=limit,
    )

    total_games = 0

    home_team_wins = 0
    away_team_wins = 0

    home_team_runs = 0
    away_team_runs = 0

    for game in games:

        home_id = game.get(
            "home_team_id"
        )

        away_id = game.get(
            "away_team_id"
        )

        home_score = game.get(
            "home_score"
        )

        away_score = game.get(
            "away_score"
        )

        if (
            home_score is None
            or away_score is None
        ):
            continue

        try:

            home_score = int(
                home_score
            )

            away_score = int(
                away_score
            )

        except (
            TypeError,
            ValueError,
        ):

            continue

        total_games += 1

        # ---------------------------------------------
        # El equipo que actualmente será HOME
        # ---------------------------------------------

        if (
            home_id == home_team_id
            and away_id == away_team_id
        ):

            home_team_runs += home_score
            away_team_runs += away_score

            if home_score > away_score:
                home_team_wins += 1
            elif away_score > home_score:
                away_team_wins += 1

        # ---------------------------------------------
        # El equipo que actualmente será HOME
        # jugó como visitante en este H2H
        # ---------------------------------------------

        elif (
            home_id == away_team_id
            and away_id == home_team_id
        ):

            home_team_runs += away_score
            away_team_runs += home_score

            if away_score > home_score:
                home_team_wins += 1
            elif home_score > away_score:
                away_team_wins += 1

    if total_games > 0:

        home_win_rate = (
            home_team_wins
            / total_games
        )

        away_win_rate = (
            away_team_wins
            / total_games
        )

        home_runs_per_game = (
            home_team_runs
            / total_games
        )

        away_runs_per_game = (
            away_team_runs
            / total_games
        )

    else:

        home_win_rate = 0
        away_win_rate = 0
        home_runs_per_game = 0
        away_runs_per_game = 0

    return {
        "games": total_games,

        "home_team": {
            "wins": home_team_wins,
            "losses": away_team_wins,
            "win_rate": round(
                home_win_rate,
                4
            ),
            "runs_scored": home_team_runs,
            "runs_allowed": away_team_runs,
            "runs_per_game": round(
                home_runs_per_game,
                3
            ),
        },

        "away_team": {
            "wins": away_team_wins,
            "losses": home_team_wins,
            "win_rate": round(
                away_win_rate,
                4
            ),
            "runs_scored": away_team_runs,
            "runs_allowed": home_team_runs,
            "runs_per_game": round(
                away_runs_per_game,
                3
            ),
        },

        "run_differential": {
            "home": (
                home_team_runs
                - away_team_runs
            ),
            "away": (
                away_team_runs
                - home_team_runs
            ),
        },

        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    }


# =========================================================
# OFFENSE VS PITCHER HAND
# =========================================================

def get_team_batting_vs_hand(
    team_id,
    pitcher_hand,
    before_date=None,
    limit=500,
):
    """
    Obtiene partidos históricos del equipo y prepara
    estadísticas ofensivas según la mano del pitcher.

    pitcher_hand:
        L = zurdo
        R = derecho

    NOTA:
    Esta primera versión utiliza los datos disponibles
    en mlb_game_history y prepara la estructura para
    incorporar estadísticas individuales de bateadores.
    """

    supabase = get_supabase_client()

    query = (
        supabase
        .table("mlb_game_history")
        .select("*")
        .eq("status", "Final")
        .or_(
            f"home_team_id.eq.{team_id},"
            f"away_team_id.eq.{team_id}"
        )
        .order(
            "game_date",
            desc=True
        )
        .limit(limit)
    )

    if before_date:

        query = query.lt(
            "game_date",
            before_date
        )

    response = query.execute()

    games = response.data or []

    # -----------------------------------------------------
    # IMPORTANTE
    # -----------------------------------------------------
    # En mlb_game_history todavía no almacenamos la mano
    # del pitcher ni estadísticas ofensivas individuales.
    #
    # Por ello no debemos inventar datos.
    #
    # Este motor devuelve la estructura preparada y deja
    # disponible la información de los partidos históricos.
    # La siguiente fase incorporará MLB player stats.
    # -----------------------------------------------------

    total_games = 0
    wins = 0
    losses = 0
    runs_scored = 0
    runs_allowed = 0

    for game in games:

        home_id = game.get(
            "home_team_id"
        )

        away_id = game.get(
            "away_team_id"
        )

        home_score = game.get(
            "home_score"
        )

        away_score = game.get(
            "away_score"
        )

        if (
            home_score is None
            or away_score is None
        ):
            continue

        try:

            home_score = int(
                home_score
            )

            away_score = int(
                away_score
            )

        except (
            TypeError,
            ValueError,
        ):

            continue

        if team_id == home_id:

            team_score = home_score
            opponent_score = away_score

        elif team_id == away_id:

            team_score = away_score
            opponent_score = home_score

        else:

            continue

        total_games += 1

        runs_scored += team_score
        runs_allowed += opponent_score

        if team_score > opponent_score:
            wins += 1
        else:
            losses += 1

    if total_games > 0:

        win_rate = (
            wins
            / total_games
        )

        runs_per_game = (
            runs_scored
            / total_games
        )

        runs_allowed_per_game = (
            runs_allowed
            / total_games
        )

    else:

        win_rate = 0
        runs_per_game = 0
        runs_allowed_per_game = 0

    return {
        "pitcher_hand": pitcher_hand,

        "available": False,

        "reason": (
            "La tabla mlb_game_history todavía "
            "no contiene la mano del pitcher ni "
            "estadísticas ofensivas individuales. "
            "Se requiere MLB player stats para "
            "calcular el split real vs LHP/RHP."
        ),

        "games": total_games,
        "wins": wins,
        "losses": losses,

        "win_rate": round(
            win_rate,
            4
        ),

        "runs_scored": runs_scored,

        "runs_allowed": runs_allowed,

        "runs_scored_per_game": round(
            runs_per_game,
            3
        ),

        "runs_allowed_per_game": round(
            runs_allowed_per_game,
            3
        ),

        "run_differential": (
            runs_scored
            - runs_allowed
        ),

        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    }


# =========================================================
# COMPLETE MATCHUP DATA
# =========================================================

def get_matchup_data(
    home_team_id,
    away_team_id,
    before_date=None,
    pitcher_hand_home=None,
    pitcher_hand_away=None,
):
    """
    Devuelve H2H y estructura de matchup para ambos equipos.

    Todavía no modifica el modelo de predicción.
    """

    h2h = calculate_h2h(
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        before_date=before_date,
        limit=10,
    )

    home_vs_hand = None
    away_vs_hand = None

    if pitcher_hand_home:

        home_vs_hand = (
            get_team_batting_vs_hand(
                team_id=home_team_id,
                pitcher_hand=pitcher_hand_home,
                before_date=before_date,
            )
        )

    if pitcher_hand_away:

        away_vs_hand = (
            get_team_batting_vs_hand(
                team_id=away_team_id,
                pitcher_hand=pitcher_hand_away,
                before_date=before_date,
            )
        )

    return {
        "h2h": h2h,

        "pitcher_matchup": {
            "home_team_vs_away_pitcher": (
                away_vs_hand
            ),
            "away_team_vs_home_pitcher": (
                home_vs_hand
            ),
        },

        "generated_at": (
            datetime.now(
                timezone.utc).isoformat()
        ),
  }
