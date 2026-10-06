from datetime import datetime, timezone

from nfl_client import get_game, build_team_history
from nfl_prediction import (
    MODEL_VERSION,
    calculate_probability,
    calculate_confidence,
)


def _parse_datetime(value):
    """
    Convierte una fecha ISO a datetime.
    """
    if not value:
        return None

    return datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )


def _calculate_data_quality(home_history, away_history):
    """
    Calcula la calidad de datos disponible para ambos equipos.

    La calidad depende del menor número de partidos históricos
    disponibles entre los dos equipos.
    """
    home_games = int(home_history.get("games", 0))
    away_games = int(away_history.get("games", 0))

    minimum_games = min(home_games, away_games)

    if minimum_games >= 5:
        return 100

    if minimum_games >= 3:
        return 85

    if minimum_games >= 1:
        return 70

    return 50


def _calculate_rest_days(history, cutoff):
    """
    Calcula los días de descanso desde el partido anterior
    hasta el kickoff del partido analizado.

    Si no existe un partido anterior, utiliza 7 días como
    valor neutral de referencia.
    """
    games_detail = history.get("games_detail") or []

    if not games_detail:
        return 7.0

    previous_kickoff = _parse_datetime(
        games_detail[0].get("kickoff")
    )

    if previous_kickoff is None:
        return 7.0

    seconds = (
        cutoff - previous_kickoff
    ).total_seconds()

    return max(0.0, seconds / 86400.0)


def analyze_nfl_game(game_id):
    """
    Ejecuta un análisis pregame NFL.

    Regla fundamental:
    ningún partido posterior al kickoff puede formar parte
    del historial utilizado para la predicción.
    """

    game = get_game(game_id)

    if not game:
        return {
            "success": False,
            "model_version": MODEL_VERSION,
            "message": "No se encontró el partido NFL.",
            "game_id": str(game_id),
        }

    kickoff = _parse_datetime(game.get("kickoff"))

    if kickoff is None:
        return {
            "success": False,
            "model_version": MODEL_VERSION,
            "message": "El partido no tiene una fecha de kickoff válida.",
            "game_id": str(game_id),
        }

    now = datetime.now(timezone.utc)

    if kickoff <= now:
        return {
            "success": False,
            "model_version": MODEL_VERSION,
            "message": (
                "El partido ya comenzó o terminó. "
                "NFL-1.0.0 solo utiliza información pre-kickoff."
            ),
            "game_id": str(game_id),
        }

    # ---------------------------------------------------------
    # Historial pregame
    # ---------------------------------------------------------

    home_history = build_team_history(
        game["home"],
        kickoff,
        game["season"],
    )

    away_history = build_team_history(
        game["away"],
        kickoff,
        game["season"],
    )

    # ---------------------------------------------------------
    # Descanso
    # ---------------------------------------------------------

    rest_home_days = _calculate_rest_days(
        home_history,
        kickoff,
    )

    rest_away_days = _calculate_rest_days(
        away_history,
        kickoff,
    )

    # ---------------------------------------------------------
    # Probabilidad
    # ---------------------------------------------------------

    probabilities = calculate_probability(
        home_history,
        away_history,
        rest_home_days,
        rest_away_days,
    )

    home_probability = probabilities["home"]
    away_probability = probabilities["away"]

    winner = (
        game["home"]
        if home_probability >= away_probability
        else game["away"]
    )

    confidence = calculate_confidence(
        probabilities
    )

    data_quality = _calculate_data_quality(
        home_history,
        away_history,
    )

    # ---------------------------------------------------------
    # Resultado completo
    # ---------------------------------------------------------

    return {
        "success": True,
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        # El cutoff representa el último instante permitido
        # para información pregame.
        "data_cutoff": kickoff.isoformat(),

        "game": game,

        "prediction": {
            "winner": winner,
            "home_probability": home_probability,
            "away_probability": away_probability,
            "confidence": confidence,
            "data_quality": data_quality,
        },

        "factors": {
            "home": home_history,
            "away": away_history,

            "rest": {
                "home_days": round(rest_home_days, 4),
                "away_days": round(rest_away_days, 4),
                "difference_days": round(
                    rest_home_days - rest_away_days,
                    4,
                ),
                "used_in_probability": True,
            },

            "quarterback": {
                "home": game.get("home_qb"),
                "away": game.get("away_qb"),
                "used_in_probability": False,
            },

            "weather": {
                "temperature": game.get("temp"),
                "wind": game.get("wind"),
                "roof": game.get("roof"),
                "surface": game.get("surface"),
                "used_in_probability": False,
            },

            "market": {
                "spread_line": game.get("spread_line"),
                "total_line": game.get("total_line"),
                "used_in_probability": False,
            },
        },
    }
