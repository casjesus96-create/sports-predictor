from datetime import datetime, timezone

from repository import get_supabase_client


def get_team_history(
    team_id,
    before_date=None,
    limit=15,
):
    """
    Obtiene los últimos partidos FINAL de un equipo
    anteriores a before_date.
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

    return response.data or []


def calculate_team_form(
    team_id,
    before_date=None,
    limit=15,
):
    """
    Calcula estadísticas recientes de un equipo.
    """

    games = get_team_history(
        team_id=team_id,
        before_date=before_date,
        limit=limit,
    )

    total = len(games)

    if total == 0:
        return {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "runs_scored": 0,
            "runs_allowed": 0,
            "run_differential": 0,
            "runs_scored_per_game": 0,
            "runs_allowed_per_game": 0,
            "home_games": 0,
            "home_wins": 0,
            "away_games": 0,
            "away_wins": 0,
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
            ValueError
        ):
            continue

        if team_id == home_id:

            team_score = home_score
            opponent_score = away_score

            home_games += 1

            if home_score > away_score:
                wins += 1
                home_wins += 1
            else:
                losses += 1

        elif team_id == away_id:

            team_score = away_score
            opponent_score = home_score

            away_games += 1

            if away_score > home_score:
                wins += 1
                away_wins += 1
            else:
                losses += 1

        else:
            continue

        runs_scored += team_score
        runs_allowed += opponent_score

    valid_games = wins + losses

    divisor = max(valid_games, 1)

    return {
        "games": valid_games,
        "wins": wins,
        "losses": losses,

        "win_rate": round(
            wins / valid_games,
            4
        ),

        "runs_scored": runs_scored,

        "runs_allowed": runs_allowed,

        "run_differential": (
            runs_scored
            - runs_allowed
        ),

        "runs_scored_per_game": round(
            runs_scored / valid_games,
            3
        ),

        "runs_allowed_per_game": round(
            runs_allowed / divisor,
            3
        ),

        "run_differential_per_game": round(
            (runs_scored - runs_allowed) / divisor,
            3
        ),

        "home_games": home_games,

        "home_wins": home_wins,

        "away_games": away_games,

        "away_wins": away_wins,
    }


def get_matchup_form(
    home_team_id,
    away_team_id,
    before_date=None,
):
    """
    Obtiene la forma reciente de ambos equipos.
    """

    home_form_5 = calculate_team_form(
        home_team_id,
        before_date,
        limit=5,
    )

    home_form_10 = calculate_team_form(
        home_team_id,
        before_date,
        limit=10,
    )

    home_form_15 = calculate_team_form(
        home_team_id,
        before_date,
        limit=15,
    )

    away_form_5 = calculate_team_form(
        away_team_id,
        before_date,
        limit=5,
    )

    away_form_10 = calculate_team_form(
        away_team_id,
        before_date,
        limit=10,
    )

    away_form_15 = calculate_team_form(
        away_team_id,
        before_date,
        limit=15,
    )

    return {
        "home": {
            "last_5": home_form_5,
            "last_10": home_form_10,
            "last_15": home_form_15,
        },

        "away": {
            "last_5": away_form_5,
            "last_10": away_form_10,
            "last_15": away_form_15,
        },

        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
  }
