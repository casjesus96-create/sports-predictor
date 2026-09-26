import requests
from datetime import datetime, timezone

from prediction import analyze_game as analyze_official_game


MLB_API = "https://statsapi.mlb.com/api/v1"
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1"
MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0",
    "Accept": "application/json",
}


def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers=MLB_HEADERS,
    )
    response.raise_for_status()
    return response.json()


def get_game(game_id):
    return get_json(f"{MLB_GAME_API}/game/{game_id}/feed/live")


def analyze_mlb_game(game_id):
    """
    Adaptador de API para el único modelo oficial.

    Este archivo ya NO calcula una segunda probabilidad.
    Toda la lógica predictiva vive en prediction.py.
    """
    game = get_game(game_id)
    game_data = game.get("gameData", {})
    status_data = game_data.get("status", {})
    status = status_data.get("abstractGameState")
    detailed_status = status_data.get("detailedState")

    if status in {"Final", "Live"}:
        return {
            "success": False,
            "message": (
                "Este partido ya comenzó o terminó. "
                "El motor pregame no utilizará información posterior al inicio."
            ),
            "game_id": str(game_id),
            "status": status,
            "detailed_status": detailed_status,
        }

    teams = game_data.get("teams", {})
    home_team = teams.get("home", {})
    away_team = teams.get("away", {})
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    home_name = home_team.get("name")
    away_name = away_team.get("name")

    datetime_value = game_data.get("datetime", {}).get("dateTime")
    venue = game_data.get("venue", {}).get("name")

    if not home_id or not away_id:
        return {
            "success": False,
            "message": "MLB no proporcionó los IDs de ambos equipos.",
            "game_id": str(game_id),
        }

    try:
        season = int(str(datetime_value)[:4]) if datetime_value else datetime.now(timezone.utc).year
    except (TypeError, ValueError):
        season = datetime.now(timezone.utc).year

    result = analyze_official_game(
        game_id=game_id,
        home_team_id=home_id,
        away_team_id=away_id,
        before_date=datetime_value,
        season=season,
        game_type="R",
    )

    if not result.get("success"):
        return result

    prediction = result.get("prediction", {})
    projected_side = prediction.get("projected_side")
    predicted_team = home_name if projected_side == "home" else away_name

    result["game"].update({
        "date": datetime_value,
        "status": status,
        "detailed_status": detailed_status,
        "venue": venue,
        "home": home_name,
        "away": away_name,
    })

    result["prediction"]["winner"] = predicted_team
    result["factors"] = {
        "signals": result.get("signals", {}),
        "matchup": result.get("matchup", {}),
        "recent_form": result.get("recent_form", {}),
    }

    return result
