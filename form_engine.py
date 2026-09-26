from datetime import datetime, timezone

import requests

from repository import get_supabase_client


MLB_API = "https://statsapi.mlb.com/api/v1"
MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0",
    "Accept": "application/json",
}


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_json(url, params=None, timeout=15):
    response = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers=MLB_HEADERS,
    )
    response.raise_for_status()
    return response.json()


def _get_game_score(game_id):
    """
    Recupera el marcador FINAL directamente desde MLB cuando
    mlb_game_history no contiene los scores.

    Esto permite reparar registros históricos antiguos sin
    depender de que una sincronización previa haya guardado
    correctamente home_score/away_score.
    """
    if not game_id:
        return None, None

    try:
        data = _get_json(
            f"{MLB_API}/schedule",
            params={
                "sportId": 1,
                "gamePk": str(game_id),
                "hydrate": "team",
            },
        )

        for date_block in data.get("dates", []):
            for game in date_block.get("games", []):
                teams = game.get("teams") or {}
                home = teams.get("home") or {}
                away = teams.get("away") or {}

                status = (game.get("status") or {}).get(
                    "abstractGameState"
                )

                if status != "Final":
                    return None, None

                return (
                    _safe_int(home.get("score")),
                    _safe_int(away.get("score")),
                )
    except Exception:
        return None, None

    return None, None


def _normalize_game_score(game):
    """Devuelve scores normalizados, con fallback a MLB Stats API."""
    home_score = _safe_int(game.get("home_score"))
    away_score = _safe_int(game.get("away_score"))

    if home_score is not None and away_score is not None:
        return home_score, away_score

    fallback_home, fallback_away = _get_game_score(
        game.get("game_id")
    )

    return fallback_home, fallback_away


def get_team_history(
    team_id,
    before_date=None,
    limit=15,
):
    """
    Obtiene hasta `limit` partidos FINAL anteriores a before_date.

    Los scores se reparan desde MLB Stats API cuando la tabla
    histórica contiene registros antiguos con scores nulos.
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
        .order("game_date", desc=True)
        .limit(max(int(limit), 1))
    )

    if before_date:
        query = query.lt("game_date", before_date)

    response = query.execute()
    games = response.data or []

    normalized = []

    for game in games:
        row = dict(game)
        home_score, away_score = _normalize_game_score(row)

        if home_score is None or away_score is None:
            continue

        row["home_score"] = home_score
        row["away_score"] = away_score
        normalized.append(row)

    return normalized


def calculate_team_form(
    team_id,
    before_date=None,
    limit=15,
    games=None,
):
    """Calcula estadísticas recientes de un equipo."""
    if games is None:
        games = get_team_history(
            team_id=team_id,
            before_date=before_date,
            limit=limit,
        )
    else:
        games = games[:limit]

    wins = 0
    losses = 0
    runs_scored = 0
    runs_allowed = 0
    home_games = 0
    home_wins = 0
    away_games = 0
    away_wins = 0

    for game in games:
        home_id = game.get("home_team_id")
        away_id = game.get("away_team_id")

        home_score = _safe_int(game.get("home_score"))
        away_score = _safe_int(game.get("away_score"))

        if home_score is None or away_score is None:
            continue

        if str(team_id) == str(home_id):
            team_score = home_score
            opponent_score = away_score
            home_games += 1

            if home_score > away_score:
                wins += 1
                home_wins += 1
            elif away_score > home_score:
                losses += 1

        elif str(team_id) == str(away_id):
            team_score = away_score
            opponent_score = home_score
            away_games += 1

            if away_score > home_score:
                wins += 1
                away_wins += 1
            elif home_score > away_score:
                losses += 1
        else:
            continue

        runs_scored += team_score
        runs_allowed += opponent_score

    valid_games = wins + losses

    if valid_games == 0:
        return {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "runs_scored": 0,
            "runs_allowed": 0,
            "run_differential": 0,
            "run_differential_per_game": 0,
            "runs_scored_per_game": 0,
            "runs_allowed_per_game": 0,
            "home_games": 0,
            "home_wins": 0,
            "away_games": 0,
            "away_wins": 0,
        }

    run_differential = runs_scored - runs_allowed

    return {
        "games": valid_games,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / valid_games, 4),
        "runs_scored": runs_scored,
        "runs_allowed": runs_allowed,
        "run_differential": run_differential,
        "run_differential_per_game": round(
            run_differential / valid_games,
            3,
        ),
        "runs_scored_per_game": round(
            runs_scored / valid_games,
            3,
        ),
        "runs_allowed_per_game": round(
            runs_allowed / valid_games,
            3,
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
    Obtiene una sola muestra de 15 partidos por equipo y deriva
    last_5/10/15 de esa muestra. Esto evita consultas repetidas
    y mantiene exactamente la misma base histórica para las tres
    ventanas.
    """
    home_games = get_team_history(
        home_team_id,
        before_date=before_date,
        limit=15,
    )

    away_games = get_team_history(
        away_team_id,
        before_date=before_date,
        limit=15,
    )

    return {
        "home": {
            "last_5": calculate_team_form(
                home_team_id,
                before_date,
                limit=5,
                games=home_games,
            ),
            "last_10": calculate_team_form(
                home_team_id,
                before_date,
                limit=10,
                games=home_games,
            ),
            "last_15": calculate_team_form(
                home_team_id,
                before_date,
                limit=15,
                games=home_games,
            ),
        },
        "away": {
            "last_5": calculate_team_form(
                away_team_id,
                before_date,
                limit=5,
                games=away_games,
            ),
            "last_10": calculate_team_form(
                away_team_id,
                before_date,
                limit=10,
                games=away_games,
            ),
            "last_15": calculate_team_form(
                away_team_id,
                before_date,
                limit=15,
                games=away_games,
            ),
        },
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }
