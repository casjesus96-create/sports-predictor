import csv
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests


SCHEDULE_URL = (
    "https://github.com/nflverse/nflverse-data/"
    "releases/download/schedules/games.csv"
)

HEADERS = {
    "User-Agent": "Sports-Predictor-NFL/1.0.0",
    "Accept": "text/csv",
}

# nflverse publica gameday/gametime como fecha y hora
# de kickoff en horario del Este de Estados Unidos.
# Convertimos esos valores a UTC para compararlos correctamente.
EASTERN_TZ = ZoneInfo("America/New_York")
UTC = timezone.utc


def _team(value):
    value = (value or "").strip().upper()

    return {
        "JAC": "JAX",
        "LA": "LAR",
    }.get(value, value)


def _float(value, default=None):
    try:
        if value is None or str(value).strip() == "":
            return default

        return float(value)

    except (TypeError, ValueError):
        return default


def _dt(date_value, time_value=None):
    """
    Convierte una fecha/hora a datetime consciente de zona
    horaria y la devuelve en UTC.

    - Si el valor ISO ya incluye zona u offset, lo respeta.
    - Si no incluye zona horaria, interpreta la hora como
      America/New_York.
    - Si recibe una fecha y una hora separadas, las combina
      en horario del Este y después las convierte a UTC.
    """

    if date_value is None:
        return None

    if isinstance(date_value, datetime):
        parsed = date_value

    else:
        value = str(date_value).strip()

        if not value:
            return None

        value = value.replace("Z", "+00:00")

        try:
            if "T" in value or " " in value:
                parsed = datetime.fromisoformat(value)

            elif time_value:
                time_text = str(time_value).strip()

                if not time_text:
                    return None

                # Admite HH:MM y HH:MM:SS.
                try:
                    parsed = datetime.fromisoformat(
                        f"{value}T{time_text}"
                    )
                except ValueError:
                    return None

            else:
                parsed = datetime.fromisoformat(value)

        except ValueError:
            return None

    # Una fecha sin zona horaria se interpreta como horario
    # del Este. Una fecha que ya tiene zona no se reemplaza.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EASTERN_TZ)

    return parsed.astimezone(UTC)


def _read():
    response = requests.get(
        SCHEDULE_URL,
        timeout=30,
        headers=HEADERS,
    )

    response.raise_for_status()

    return list(
        csv.DictReader(
            io.StringIO(response.text)
        )
    )


def _normalize(row):
    kickoff = _dt(
        row.get("gameday"),
        row.get("gametime"),
    )

    try:
        season = int(row["season"])
    except (KeyError, TypeError, ValueError):
        return None

    return {
        "game_id": row.get("game_id"),
        "season": season,
        "game_type": row.get("game_type"),
        "week": row.get("week"),
        "kickoff": (
            kickoff.isoformat()
            if kickoff
            else None
        ),
        "gameday": row.get("gameday"),
        "gametime": row.get("gametime"),
        "away": _team(row.get("away_team")),
        "home": _team(row.get("home_team")),
        "away_score": _float(
            row.get("away_score")
        ),
        "home_score": _float(
            row.get("home_score")
        ),
        "stadium": row.get("stadium"),
        "roof": row.get("roof"),
        "surface": row.get("surface"),
        "temp": _float(row.get("temp")),
        "wind": _float(row.get("wind")),
        "spread_line": _float(
            row.get("spread_line")
        ),
        "total_line": _float(
            row.get("total_line")
        ),
        "away_qb": row.get("away_qb_name"),
        "home_qb": row.get("home_qb_name"),
    }


def load_schedule(season=2026):
    rows = _read()
    games = []

    for row in rows:
        if str(row.get("season")) != str(season):
            continue

        game = _normalize(row)

        if game is not None:
            games.append(game)

    return games


def get_game(game_id, season=2026):
    return next(
        (
            game
            for game in load_schedule(season)
            if str(game.get("game_id")) == str(game_id)
        ),
        None,
    )


def get_upcoming_games(season=2026, limit=20):
    now = datetime.now(UTC)

    games = [
        game
        for game in load_schedule(season)
        if (
            game.get("game_type")
            in {"REG", "WC", "DIV", "CON", "SB"}
            and game.get("kickoff")
            and _dt(game["kickoff"]) > now
        )
    ]

    return sorted(
        games,
        key=lambda game: game["kickoff"],
    )[:limit]


def get_completed_games_before(
    team,
    cutoff,
    season=2026,
):
    team = _team(team)

    cutoff_utc = _dt(cutoff)

    if cutoff_utc is None:
        return []

    completed = []

    for game in load_schedule(season):
        if game.get("game_type") != "REG":
            continue

        if team not in {
            game.get("home"),
            game.get("away"),
        }:
            continue

        home_score = game.get("home_score")
        away_score = game.get("away_score")
        kickoff = _dt(game.get("kickoff"))

        if (
            home_score is None
            or away_score is None
            or kickoff is None
        ):
            continue

        # Solo incluir partidos anteriores al kickoff
        # del partido que se está analizando.
        if kickoff >= cutoff_utc:
            continue

        completed.append(game)

    return sorted(
        completed,
        key=lambda game: game["kickoff"],
        reverse=True,
    )


def build_team_history(
    team,
    cutoff,
    season=2026,
):
    games = get_completed_games_before(
        team,
        cutoff,
        season,
    )

    team = _team(team)

    wins = 0
    losses = 0
    points_for = 0.0
    points_against = 0.0
    detail = []

    for game in games:
        away_score = game["away_score"]
        home_score = game["home_score"]

        if game["home"] == team:
            team_points = home_score
            opponent_points = away_score
        else:
            team_points = away_score
            opponent_points = home_score

        points_for += team_points
        points_against += opponent_points

        if team_points > opponent_points:
            wins += 1
        else:
            losses += 1

        detail.append({
            "game_id": game["game_id"],
            "kickoff": game["kickoff"],
            "point_diff": (
                team_points - opponent_points
            ),
        })

    total_games = wins + losses
    recent_games = detail[:5]

    if total_games:
        win_rate = wins / total_games
        points_for_per_game = (
            points_for / total_games
        )
        points_against_per_game = (
            points_against / total_games
        )
        point_diff_per_game = (
            points_for - points_against
        ) / total_games
    else:
        win_rate = 0.5
        points_for_per_game = 21.0
        points_against_per_game = 21.0
        point_diff_per_game = 0.0

    if recent_games:
        recent_win_rate = (
            sum(
                game["point_diff"] > 0
                for game in recent_games
            )
            / len(recent_games)
        )

        recent_point_diff_per_game = (
            sum(
                game["point_diff"]
                for game in recent_games
            )
            / len(recent_games)
        )
    else:
        recent_win_rate = 0.5
        recent_point_diff_per_game = 0.0

    return {
        "team": team,
        "games": total_games,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "points_for_per_game": round(
            points_for_per_game,
            4,
        ),
        "points_against_per_game": round(
            points_against_per_game,
            4,
        ),
        "point_diff_per_game": round(
            point_diff_per_game,
            4,
        ),
        "recent_games": len(recent_games),
        "recent_win_rate": round(
            recent_win_rate,
            4,
        ),
        "recent_point_diff_per_game": round(
            recent_point_diff_per_game,
            4,
        ),
        "games_detail": detail,
    }
