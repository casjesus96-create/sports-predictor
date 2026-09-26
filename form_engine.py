from datetime import datetime, timezone, timedelta
import requests


MLB_API = "https://statsapi.mlb.com/api/v1"

MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0",
    "Accept": "application/json",
}


def _safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_json(url, params=None, timeout=20):
    response = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers=MLB_HEADERS,
    )
    response.raise_for_status()
    return response.json()


def _parse_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except ValueError:
        return None


def _normalize_before_date(before_date):
    if before_date is None:
        return None

    parsed = _parse_datetime(before_date)

    if parsed is None:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _season_from_before_date(before_date):
    parsed = _normalize_before_date(before_date)

    if parsed is not None:
        return parsed.year

    return datetime.now(timezone.utc).year


def _extract_game_score(game):
    teams = game.get("teams") or {}

    home = teams.get("home") or {}
    away = teams.get("away") or {}

    home_score = _safe_int(home.get("score"))
    away_score = _safe_int(away.get("score"))

    return home_score, away_score


def _game_is_before_cutoff(game, before_dt):
    if before_dt is None:
        return True

    game_dt = _parse_datetime(
        game.get("gameDate")
    )

    if game_dt is None:
        return False

    if game_dt.tzinfo is None:
        game_dt = game_dt.replace(
            tzinfo=timezone.utc
        )

    return (
        game_dt.astimezone(timezone.utc)
        < before_dt
    )


def _fetch_schedule_window(
    team_id,
    start_date,
    end_date,
    before_dt=None,
):
    """
    Consulta un rango corto del calendario MLB.

    Usamos ventanas pequeñas deliberadamente. Esto evita depender
    de respuestas demasiado grandes del endpoint /schedule.
    """

    team_id = _safe_int(team_id)

    if team_id is None:
        return []

    try:
        data = _get_json(
            f"{MLB_API}/schedule",
            params={
                "sportId": 1,
                "teamId": team_id,
                "startDate": start_date,
                "endDate": end_date,
                "gameTypes": "R",
                "hydrate": "team,linescore",
            },
        )
    except Exception:
        return []

    games = []

    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            status = (
                game.get("status") or {}
            ).get("abstractGameState")

            if status != "Final":
                continue

            if not _game_is_before_cutoff(
                game,
                before_dt,
            ):
                continue

            teams = game.get("teams") or {}

            home = teams.get("home") or {}
            away = teams.get("away") or {}

            home_team = home.get("team") or {}
            away_team = away.get("team") or {}

            home_id = _safe_int(
                home_team.get("id")
            )
            away_id = _safe_int(
                away_team.get("id")
            )

            if (
                home_id != team_id
                and away_id != team_id
            ):
                continue

            home_score, away_score = (
                _extract_game_score(game)
            )

            if (
                home_score is None
                or away_score is None
            ):
                continue

            games.append({
                "game_id": str(
                    game.get("gamePk")
                ),
                "game_date": game.get(
                    "gameDate"
                ),
                "home_team_id": home_id,
                "home_team": home_team.get(
                    "name"
                ),
                "away_team_id": away_id,
                "away_team": away_team.get(
                    "name"
                ),
                "home_score": home_score,
                "away_score": away_score,
                "status": status,
                "detailed_status": (
                    game.get("status") or {}
                ).get("detailedState"),
                "source": "mlb_stats_api",
            })

    return games


def get_team_history(
    team_id,
    before_date=None,
    limit=15,
):
    """
    Obtiene los últimos partidos FINAL anteriores al partido
    que se está analizando.

    La consulta se hace en ventanas de 30 días hacia atrás hasta
    encontrar suficientes partidos. Así no dependemos de una
    consulta enorme desde marzo hasta septiembre.

    Fuente canónica:
        MLB Stats API

    No depende de mlb_game_history.
    """

    try:
        limit = max(int(limit), 1)
    except (TypeError, ValueError):
        limit = 15

    before_dt = _normalize_before_date(
        before_date
    )

    if before_dt is None:
        before_dt = datetime.now(
            timezone.utc
        )

    season = before_dt.year

    # No buscamos antes del inicio de la temporada MLB.
    season_start = datetime(
        season,
        3,
        1,
        tzinfo=timezone.utc,
    )

    # Empezamos justo antes del día del partido.
    cursor_end = before_dt.date()

    collected = {}

    # Hasta 6 ventanas de 30 días = 180 días.
    # Es suficiente para encontrar 15 partidos incluso con
    # periodos de baja actividad.
    for _ in range(6):
        cursor_start = (
            cursor_end
            - timedelta(days=30)
        )

        if cursor_start < season_start.date():
            cursor_start = season_start.date()

        start_text = (
            cursor_start.isoformat()
        )
        end_text = (
            cursor_end.isoformat()
        )

        window_games = _fetch_schedule_window(
            team_id=team_id,
            start_date=start_text,
            end_date=end_text,
            before_dt=before_dt,
        )

        for game in window_games:
            game_id = game.get("game_id")

            if game_id:
                collected[game_id] = game

        if len(collected) >= limit:
            break

        if cursor_start <= season_start.date():
            break

        # Evita volver a consultar exactamente el mismo día.
        cursor_end = (
            cursor_start
            - timedelta(days=1)
        )

    games = list(
        collected.values()
    )

    games.sort(
        key=lambda row: (
            _parse_datetime(
                row.get("game_date")
            )
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        ),
        reverse=True,
    )

    return games[:limit]


def calculate_team_form(
    team_id,
    before_date=None,
    limit=15,
    games=None,
):
    """
    Calcula forma reciente usando partidos reales FINAL.
    """

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

    valid_games = 0

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

        else:
            continue

        valid_games += 1

        runs_scored += team_score
        runs_allowed += opponent_score

    if valid_games == 0:
        return {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "runs_scored": 0,
            "runs_allowed": 0,
            "run_differential": 0,
            "run_differential_per_game": 0.0,
            "runs_scored_per_game": 0.0,
            "runs_allowed_per_game": 0.0,
            "home_games": 0,
            "home_wins": 0,
            "away_games": 0,
            "away_wins": 0,
        }

    run_differential = (
        runs_scored
        - runs_allowed
    )

    return {
        "games": valid_games,
        "wins": wins,
        "losses": losses,
        "win_rate": round(
            wins / valid_games,
            4,
        ),
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
    Obtiene una muestra única de 15 partidos por equipo y genera
    las ventanas de 5, 10 y 15.

    Las tres ventanas utilizan exactamente la misma secuencia
    histórica, evitando inconsistencias entre consultas.
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
        "source": "MLB Stats API",
    }
