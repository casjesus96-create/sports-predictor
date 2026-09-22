import requests
from datetime import datetime, timezone

from pitcher_engine import get_game_pitchers
from repository import get_supabase_client
from split_engine import get_team_batting_split


MLB_API = "https://statsapi.mlb.com/api/v1"


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _get_json(url, params=None, timeout=30):
    response = requests.get(
        url,
        params=params,
        timeout=timeout,
    )

    response.raise_for_status()

    return response.json()


def get_h2h_games(
    home_team_id,
    away_team_id,
    before_date=None,
    limit=20,
):
    """
    Obtiene enfrentamientos directos entre dos equipos
    anteriores a before_date.

    Se utilizan únicamente partidos FINAL.
    """

    supabase = get_supabase_client()

    home_team_id = _safe_int(home_team_id)
    away_team_id = _safe_int(away_team_id)

    if home_team_id is None or away_team_id is None:
        return []

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
            desc=True,
        )
        .limit(limit)
    )

    if before_date:
        query = query.lt(
            "game_date",
            before_date,
        )

    response = query.execute()

    return response.data or []


def calculate_h2h(
    home_team_id,
    away_team_id,
    before_date=None,
    limit=20,
):
    """
    Calcula estadísticas de enfrentamientos directos.
    """

    games = get_h2h_games(
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        before_date=before_date,
        limit=limit,
    )

    home_team_id = _safe_int(home_team_id)
    away_team_id = _safe_int(away_team_id)

    home_wins = 0
    away_wins = 0

    home_runs = 0
    away_runs = 0

    valid_games = 0

    for game in games:
        home_id = _safe_int(
            game.get("home_team_id")
        )

        away_id = _safe_int(
            game.get("away_team_id")
        )

        home_score = game.get("home_score")
        away_score = game.get("away_score")

        if home_score is None or away_score is None:
            continue

        home_score = _safe_int(home_score)
        away_score = _safe_int(away_score)

        if home_score is None or away_score is None:
            continue

        valid_games += 1

        if home_id == home_team_id:
            home_team_score = home_score
            away_team_score = away_score

        elif home_id == away_team_id:
            home_team_score = away_score
            away_team_score = home_score

        else:
            continue

        home_runs += home_team_score
        away_runs += away_team_score

        if home_team_score > away_team_score:
            home_wins += 1
        elif away_team_score > home_team_score:
            away_wins += 1

    run_differential = (
        home_runs - away_runs
    )

    return {
        "available": valid_games > 0,
        "games": valid_games,
        "home_team_wins": home_wins,
        "away_team_wins": away_wins,
        "home_team_runs": home_runs,
        "away_team_runs": away_runs,
        "home_team_run_differential": run_differential,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def get_team_general_context(
    team_id,
    before_date=None,
    limit=200,
):
    """
    Obtiene contexto histórico general del equipo.
    """

    games = (
        get_team_history(
            team_id=team_id,
            before_date=before_date,
            limit=limit,
        )
    )

    wins = 0
    losses = 0

    runs_scored = 0
    runs_allowed = 0

    for game in games:
        home_id = _safe_int(
            game.get("home_team_id")
        )

        away_id = _safe_int(
            game.get("away_team_id")
        )

        home_score = _safe_int(
            game.get("home_score")
        )

        away_score = _safe_int(
            game.get("away_score")
        )

        if (
            home_score is None
            or away_score is None
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

        runs_scored += team_score
        runs_allowed += opponent_score

        if team_score > opponent_score:
            wins += 1
        else:
            losses += 1

    games_count = wins + losses

    return {
        "available": games_count > 0,
        "games": games_count,
        "wins": wins,
        "losses": losses,
        "win_rate": round(
            wins / games_count,
            4,
        ) if games_count else 0,
        "runs_scored": runs_scored,
        "runs_allowed": runs_allowed,
        "run_differential": (
            runs_scored - runs_allowed
        ),
        "runs_scored_per_game": round(
            runs_scored / games_count,
            3,
        ) if games_count else 0,
        "runs_allowed_per_game": round(
            runs_allowed / games_count,
            3,
        ) if games_count else 0,
    }


def get_team_history(
    team_id,
    before_date=None,
    limit=200,
):
    """
    Obtiene partidos FINAL de un equipo
    anteriores a before_date.
    """

    supabase = get_supabase_client()

    team_id = _safe_int(team_id)

    if team_id is None:
        return []

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
            desc=True,
        )
        .limit(limit)
    )

    if before_date:
        query = query.lt(
            "game_date",
            before_date,
        )

    response = query.execute()

    return response.data or []


def get_matchup_batting_splits(
    home_team_id,
    away_team_id,
    home_pitcher_hand,
    away_pitcher_hand,
    season,
    game_type="R",
):
    """
    Obtiene los splits ofensivos correctos
    según la mano del pitcher rival.

    Equipo local:
        batea contra pitcher visitante.

    Equipo visitante:
        batea contra pitcher local.
    """

    home_team_id = _safe_int(home_team_id)
    away_team_id = _safe_int(away_team_id)

    home_pitcher_hand = str(
        home_pitcher_hand or ""
    ).upper()

    away_pitcher_hand = str(
        away_pitcher_hand or ""
    ).upper()

    home_vs_away_pitcher = {
        "available": False,
        "reason": (
            "No se conoce la mano del pitcher visitante."
        ),
    }

    away_vs_home_pitcher = {
        "available": False,
        "reason": (
            "No se conoce la mano del pitcher local."
        ),
    }

    if away_pitcher_hand in ("R", "L"):
        home_vs_away_pitcher = (
            get_team_batting_split(
                team_id=home_team_id,
                season=season,
                pitcher_hand=away_pitcher_hand,
                game_type=game_type,
            )
        )

    if home_pitcher_hand in ("R", "L"):
        away_vs_home_pitcher = (
            get_team_batting_split(
                team_id=away_team_id,
                season=season,
                pitcher_hand=home_pitcher_hand,
                game_type=game_type,
            )
        )

    return {
        "home_team": {
            "team_id": home_team_id,
            "pitcher_faced": away_pitcher_hand,
            "batting_split": home_vs_away_pitcher,
        },
        "away_team": {
            "team_id": away_team_id,
            "pitcher_faced": home_pitcher_hand,
            "batting_split": away_vs_home_pitcher,
        },
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def get_matchup_data(
    game_id,
    home_team_id,
    away_team_id,
    before_date=None,
    season=None,
    game_type="R",
):
    """
    Construye todos los datos relevantes del matchup:

    - Pitchers probables
    - Mano de cada pitcher
    - H2H
    - Contexto general de cada equipo
    - Splits ofensivos contra la mano del pitcher rival
    """

    game_id = _safe_int(game_id)
    home_team_id = _safe_int(home_team_id)
    away_team_id = _safe_int(away_team_id)

    if game_id is None:
        raise ValueError("game_id inválido.")

    if home_team_id is None:
        raise ValueError("home_team_id inválido.")

    if away_team_id is None:
        raise ValueError("away_team_id inválido.")

    if season is None:
        if before_date:
            try:
                season = int(
                    str(before_date)[:4]
                )
            except (TypeError, ValueError):
                season = datetime.now(
                    timezone.utc
                ).year
        else:
            season = datetime.now(
                timezone.utc
            ).year

    pitchers = get_game_pitchers(
        game_id
    )

    home_pitcher = (
        pitchers.get("home_pitcher")
        or {}
    )

    away_pitcher = (
        pitchers.get("away_pitcher")
        or {}
    )

    home_pitcher_hand = (
        home_pitcher.get("pitcher_hand")
    )

    away_pitcher_hand = (
        away_pitcher.get("pitcher_hand")
    )

    h2h = calculate_h2h(
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        before_date=before_date,
        limit=20,
    )

    home_context = get_team_general_context(
        team_id=home_team_id,
        before_date=before_date,
        limit=200,
    )

    away_context = get_team_general_context(
        team_id=away_team_id,
        before_date=before_date,
        limit=200,
    )

    batting_splits = (
        get_matchup_batting_splits(
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_pitcher_hand=home_pitcher_hand,
            away_pitcher_hand=away_pitcher_hand,
            season=season,
            game_type=game_type,
        )
    )

    return {
        "available": True,
        "game_id": game_id,
        "season": season,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,

        "pitchers": {
            "home": home_pitcher,
            "away": away_pitcher,
        },

        "pitcher_hands": {
            "home": home_pitcher_hand,
            "away": away_pitcher_hand,
        },

        "h2h": h2h,

        "general_context": {
            "home": home_context,
            "away": away_context,
        },

        "batting_splits": batting_splits,

        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }
