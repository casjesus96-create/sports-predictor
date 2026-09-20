import requests

from repository import (
    get_pending_predictions,
    settle_prediction,
)


MLB_API = "https://statsapi.mlb.com/api/v1"

HEADERS = {
    "User-Agent": "Sports-Predictor/1.0"
}


def get_mlb_game(game_id):
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


def settle_game(game_id):
    game_id = str(game_id)

    game = get_mlb_game(game_id)

    if not game:
        print(
            f"[SKIP] MLB no encontró el partido {game_id}"
        )

        return {
            "success": False,
            "reason": "NOT_FOUND",
            "event_id": game_id,
        }

    game_data = game.get("gameData", {})
    live_data = game.get("liveData", {})

    status = (
        game_data
        .get("status", {})
        .get("abstractGameState")
    )

    detailed_status = (
        game_data
        .get("status", {})
        .get("detailedState")
    )

    if status != "Final":
        print(
            f"[PENDING] {game_id}: "
            f"{status} / {detailed_status}"
        )

        return {
            "success": False,
            "reason": "NOT_FINAL",
            "event_id": game_id,
            "status": status,
            "detailed_status": detailed_status,
        }

    teams = game_data.get("teams", {})

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

    scores = linescore.get(
        "teams",
        {}
    )

    home_score = (
        scores
        .get("home", {})
        .get("runs")
    )

    away_score = (
        scores
        .get("away", {})
        .get("runs")
    )

    if home_score is None or away_score is None:
        print(
            f"[WAIT] {game_id}: "
            "partido Final pero sin marcador completo"
        )

        return {
            "success": False,
            "reason": "NO_SCORE",
            "event_id": game_id,
        }

    home_score = int(home_score)
    away_score = int(away_score)

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

    result = settle_prediction(
        event_id=game_id,
        actual_winner=actual_winner,
        actual_home_score=home_score,
        actual_away_score=away_score,
    )

    if not result.get("updated"):
        print(
            f"[SKIP] {game_id}: "
            f"{result.get('reason')}"
        )

        return {
            "success": False,
            "reason": "NOT_UPDATED",
            "event_id": game_id,
            "details": result,
        }

    prediction_result = result.get(
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

        result = settle_game(event_id)

        if result.get("success"):
            settled += 1

        elif result.get("reason") == "NOT_FINAL":
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
