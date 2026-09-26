from datetime import datetime, timezone, date
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


def _safe_float(value, default=0.0):
    try:
        return float(value)
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

    text = str(value).strip()

    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
    except ValueError:
        return None


def _normalize_before_date(before_date):
    """
    Convierte before_date a datetime UTC cuando es posible.

    Se utiliza solamente como límite temporal para evitar
    data leakage.
    """
    if before_date is None:
        return None

    parsed = _parse_datetime(before_date)

    if parsed is None:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _season_from_before_date(before_date):
    """
    Determina la temporada MLB a partir del partido analizado.
    """
    parsed = _normalize_before_date(before_date)

    if parsed is not None:
        return parsed.year

    return datetime.now(timezone.utc).year


def _season_start_date(season):
    """
    Inicio de temporada suficientemente temprano para cubrir
    toda la temporada regular.
    """
    return f"{int(season)}-03-01"


def _extract_game_score(game):
    """
    Extrae marcador final directamente del objeto de MLB Stats API.
    """
    teams = game.get("teams") or {}

    home = teams.get("home") or {}
    away = teams.get("away") or {}

    home_score = _safe_int(home.get("score"))
    away_score = _safe_int(away.get("score"))

    if home_score is None or away_score is None:
        return None, None

    return home_score, away_score


def _game_is_before_cutoff(game, before_dt):
    """
    Evita utilizar información posterior al momento de análisis.
    """
    if before_dt is None:
        return True

    game_dt = _parse_datetime(game.get("gameDate"))

    if game_dt is None:
        return False

    if game_dt.tzinfo is None:
        game_dt = game_dt.replace(tzinfo=timezone.utc)

    game_dt = game_dt.astimezone(timezone.utc)

    return game_dt < before_dt


def _fetch_team_recent_games_from_mlb(
    team_id,
    before_date=None,
    season=None,
    limit=15,
):
    """
    Fuente canónica de forma reciente.

    IMPORTANTE:
    No depende de mlb_game_history.

    MLB Stats API permite consultar el calendario por teamId,
    startDate/endDate y gameTypes. Los marcadores vienen en
    teams.home.score / teams.away.score.
    """
    team_id = _safe_int(team_id)

    if team_id is None:
        return []

    before_dt = _normalize_before_date(before_date)

    if season is None:
        season = _season_from_before_date(before_date)

    season = int(season)

    if before_dt is not None:
        end_date = before_dt.date().isoformat()
    else:
        end_date = datetime.now(
            timezone.utc
        ).date().isoformat()

    try:
        data = _get_json(
            f"{MLB_API}/schedule",
            params={
                "sportId": 1,
                "teamId": team_id,
                "startDate": _season_start_date(season),
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

            home = (
                (game.get("teams") or {})
                .get("home") or {}
            )

            away = (
                (game.get("teams") or {})
                .get("away") or {}
            )

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

    return games[:max(int(limit), 1)]


def _get_game_score(game_id):
    """
    Fallback individual para un partido concreto.

    Se utiliza solamente si una respuesta de calendario no trae
    el marcador.
    """
    if not game_id:
        return None, None

    try:
        data = _get_json(
            f"{MLB_API}/schedule",
            params={
                "sportId": 1,
                "gamePk": str(game_id),
                "hydrate": "team,linescore",
            },
        )
    except Exception:
        return None, None

    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            status = (
                game.get("status") or {}
            ).get("abstractGameState")

            if status != "Final":
                continue

            return _extract_game_score(game)

    return None, None


def get_team_history(
    team_id,
    before_date=None,
    limit=15,
):
    """
    Obtiene los últimos partidos FINAL de un equipo.

    La fuente principal es MLB Stats API, no la tabla local.
    Esto evita que una tabla histórica incompleta o con scores
    nulos destruya la forma reciente del modelo.
    """
    games = _fetch_team_recent_games_from_mlb(
        team_id=team_id,
        before_date=before_date,
        season=_season_from_before_date(
            before_date
        ),
        limit=limit,
    )

    return games


def calculate_team_form(
    team_id,
    before_date=None,
    limit=15,
    games=None,
):
    """
    Calcula estadísticas recientes de un equipo.
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
            elif home_score > away_score:
                losses += 1
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
        runs_scored - runs_allowed
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
    Obtiene una sola muestra de 15 partidos por equipo y deriva
    last_5/10/15 de esa muestra.

    Los datos proceden directamente de MLB Stats API y quedan
    limitados estrictamente por before_date.
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
