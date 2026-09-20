import requests

from repository import (
    get_pending_predictions,
    settle_prediction,
)


MLB_API = "https://statsapi.mlb.com/api/v1"

HEADERS = {
    "User-Agent": "Sports-Predictor/1.0"
}


def get_schedule_game(game_id):
    """
    Obtiene un partido directamente mediante gamePk
    usando el endpoint Schedule de MLB.
    """

    url = f"{MLB_API}/schedule"

    params = {
        "sportId": 1,
        "gamePk": str(game_id),
        "hydrate": "team,venue,probablePitcher",
    }

    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers=HEADERS,
    )

    if response.status_code == 404:
        return None

    response.raise_for_status()

    data = response.json()

    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            if str(game.get("gamePk")) == str(game_id):
                return game

    return None


def get_live_game(game_id):
    """
    Segunda fuente de información.
    Se utiliza si Schedule no proporciona
    todos los datos necesarios.
    """

    url = f"{MLB_API}/game/{game_id}/feed/live"

    response = requests.get(
        url,
        timeout=20,
        headers=HEADERS,
    )

    if response.status_code == 404:
        return None

    response.raise_for_status()

    return response.json()


def extract_game_result_from_schedule(game):
    """
    Extrae estado, equipos y marcador desde Schedule.
    """

    if not game:
        return None

    status_data = game.get("status", {})

    status = status_data.get(
        "abstractGameState"
    )

    detailed_status = status_data.get(
        "detailedState"
    )

    teams = game.get("teams", {})

    home_data = teams.get("home", {})
    away_data = teams.get("away", {})

    home_team_data = home_data.get(
        "team",
        {}
    )

    away_team_data = away_data.get(
        "team",
        {}
    )

    home_team = home_team_data.get(
        "name"
    )

    away_team = away_team_data.get(
        "name"
    )

    home_score = home_data.get(
        "score"
    )

    away_score = away_data.get(
        "score"
    )

    return {
        "status": status,
        "detailed_status": detailed_status,
        "home": home_team,
        "away": away_team,
        "home_score": home_score,
        "away_score": away_score,
    }


def extract_game_result_from_live(game):
    """
    Extrae estado, equipos y marcador desde feed/live.
    """

    if not game:
        return None

    game_data = game.get(
        "gameData",
        {}
    )

    live_data = game.get(
        "liveData",
        {}
    )

    status_data = game_data.get(
        "status",
        {}
    )

    status = status_data.get(
        "abstractGameState"
    )

    detailed_status = status_data.get(
        "detailedState"
    )

    teams = game_data.get(
        "teams",
        {}
    )

    home_team = (
        teams
        .get("home", {})
        .get("name")
    )

    away_team = (
        teams
        .get("away", {})
        .get("name")
    )

    linescore = live_data.get(
        "linescore",
        {}
    )

    score_teams = linescore.get(
        "teams",
        {}
    )

    home_score = (
        score_teams
        .get("home", {})
        .get("runs")
    )

    away_score = (
        score_teams
        .get("away", {})
        .get("runs")
    )

    return {
        "status": status,
        "detailed_status": detailed_status,
        "home": home_team,
        "away": away_team,
        "home_score": home_score,
        "away_score": away_score,
    }


def get_game_result(game_id):
    """
    Obtiene el resultado de un partido.

    Prioridad:
    1. MLB Schedule
    2. MLB feed/live
    """

    schedule_game = get_schedule_game(
        game_id
    )

    if schedule_game:

        result = extract_game_result_from_schedule(
            schedule_game
        )

        if result:
            return result

    live_game = get_live_game(
        game_id
    )

    if live_game:

        result = extract_game_result_from_live(
            live_game
        )

        if result:
            return result

    return None


def settle_game(game_id):

    game_id = str(game_id)

    try:
        result = get_game_result(
            game_id
        )

    except requests.exceptions.RequestException as exc:

        print(
            f"[ERROR] MLB API para {game_id}: "
            f"{exc}"
        )

        return {
            "success": False,
            "reason": "MLB_API_ERROR",
            "event_id": game_id,
            "details": str(exc),
        }

    if not result:

        print(
            f"[SKIP] MLB no encontró el partido "
            f"{game_id}"
        )

        return {
            "success": False,
            "reason": "NOT_FOUND",
            "event_id": game_id,
        }

    status = result.get(
        "status"
    )

    detailed_status = result.get(
        "detailed_status"
    )

    home_team = result.get(
        "home"
    )

    away_team = result.get(
        "away"
    )

    home_score = result.get(
        "home_score"
    )

    away_score = result.get(
        "away_score"
    )

    print(
        f"[CHECK] {game_id}: "
        f"{away_team} @ {home_team} | "
        f"{status} / {detailed_status} | "
        f"{away_score}-{home_score}"
    )

    if status != "Final":

        print(
            f"[PENDING] {game_id}: "
            f"el partido todavía no es Final"
        )

        return {
            "success": False,
            "reason": "NOT_FINAL",
            "event_id": game_id,
            "status": status,
            "detailed_status": detailed_status,
            "home": home_team,
            "away": away_team,
            "home_score": home_score,
            "away_score": away_score,
        }

    if home_score is None or away_score is None:

        print(
            f"[WAIT] {game_id}: "
            "partido Final pero sin marcador completo"
        )

        return {
            "success": False,
            "reason": "NO_SCORE",
            "event_id": game_id,
            "home": home_team,
            "away": away_team,
        }

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

        print(
            f"[WAIT] {game_id}: "
            "marcador inválido"
        )

        return {
            "success": False,
            "reason": "INVALID_SCORE",
            "event_id": game_id,
            "home_score": home_score,
            "away_score": away_score,
        }

    if home_score > away_score:

        actual_winner = home_team

    elif away_score > home_score:

        actual_winner = away_team

    else:

        print(
            f"[WAIT] {game_id}: "
            "marcador empatado"
        )

        return {
            "success": False,
            "reason": "TIE",
            "event_id": game_id,
        }

    settlement = settle_prediction(
        event_id=game_id,
        actual_winner=actual_winner,
        actual_home_score=home_score,
        actual_away_score=away_score,
    )

    if not settlement.get(
        "updated"
    ):

        print(
            f"[SKIP] {game_id}: "
            f"{settlement.get('reason')}"
        )

        return {
            "success": False,
            "reason": "NOT_UPDATED",
            "event_id": game_id,
            "details": settlement,
        }

    prediction_result = settlement.get(
        "prediction_result"
    )

    print(
        f"[SETTLED] {game_id}: "
        f"{away_team} {away_score} - "
        f"{home_team} {home_score} | "
        f"Winner: {actual_winner} | "
        f"Prediction: {prediction_result}"
    )

    return {
        "success": True,
        "event_id": game_id,
        "home": home_team,
        "away": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "actual_winner": actual_winner,
        "prediction_result": prediction_result,
    }


def main():

    print(
        "===================================="
    )

    print(
        " SPORTS PREDICTOR - SETTLEMENT JOB"
    )

    print(
        "===================================="
    )

    predictions = get_pending_predictions()

    print(
        f"Predicciones PENDING encontradas: "
        f"{len(predictions)}"
    )

    settled = 0
    pending = 0
    skipped = 0

    for prediction in predictions:

        event_id = prediction.get(
            "event_id"
        )

        if not event_id:

            print(
                "[SKIP] Predicción sin event_id"
            )

            skipped += 1

            continue

        result = settle_game(
            event_id
        )

        if result.get(
            "success"
        ):

            settled += 1

        elif result.get(
            "reason"
        ) == "NOT_FINAL":

            pending += 1

        else:

            skipped += 1

    print(
        "------------------------------------"
    )

    print(
        f"Liquidaciones realizadas: {settled}"
    )

    print(
        f"Partidos aún pendientes: {pending}"
    )

    print(
        f"Partidos omitidos: {skipped}"
    )

    print(
        "===================================="
    )


if __name__ == "__main__":
    main()
