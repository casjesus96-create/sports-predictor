import os
from datetime import datetime, timedelta, timezone

import requests
from supabase import create_client


MLB_API = "https://statsapi.mlb.com/api/v1"

HEADERS = {
    "User-Agent": "Sports-Predictor/1.0"
}


def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY"
        )

    return create_client(url, key)


def get_schedule(start_date, end_date):
    """
    Obtiene partidos MLB dentro de un rango de fechas.
    """

    url = f"{MLB_API}/schedule"

    params = {
        "sportId": 1,
        "startDate": start_date,
        "endDate": end_date,
        "hydrate": "team,venue",
    }

    response = requests.get(
        url,
        params=params,
        timeout=30,
        headers=HEADERS,
    )

    response.raise_for_status()

    return response.json()


def extract_games(data):
    """
    Convierte la respuesta de MLB en registros
    compatibles con mlb_game_history.
    """

    games = []

    for date_block in data.get("dates", []):

        for game in date_block.get("games", []):

            game_pk = game.get("gamePk")

            if not game_pk:
                continue

            status_data = game.get(
                "status",
                {}
            )

            teams = game.get(
                "teams",
                {}
            )

            home_data = teams.get(
                "home",
                {}
            )

            away_data = teams.get(
                "away",
                {}
            )

            home_team_data = home_data.get(
                "team",
                {}
            )

            away_team_data = away_data.get(
                "team",
                {}
            )

            home_team_id = home_team_data.get(
                "id"
            )

            away_team_id = away_team_data.get(
                "id"
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

            home_winner = None

            if (
                home_score is not None
                and away_score is not None
            ):

                try:

                    home_score_int = int(
                        home_score
                    )

                    away_score_int = int(
                        away_score
                    )

                    if home_score_int > away_score_int:
                        home_winner = True

                    elif home_score_int < away_score_int:
                        home_winner = False

                except (
                    TypeError,
                    ValueError
                ):
                    home_winner = None

            game_date = game.get(
                "gameDate"
            )

            season = game.get(
                "season"
            )

            if season is None and game_date:

                try:
                    season = int(
                        game_date[:4]
                    )
                except (
                    TypeError,
                    ValueError
                ):
                    season = None

            venue = (
                game.get("venue", {})
                .get("name")
            )

            games.append(
                {
                    "game_id": str(game_pk),

                    "game_date": game_date,

                    "season": season,

                    "home_team_id": home_team_id,

                    "home_team": home_team,

                    "away_team_id": away_team_id,

                    "away_team": away_team,

                    "home_score": (
                        int(home_score)
                        if home_score is not None
                        else None
                    ),

                    "away_score": (
                        int(away_score)
                        if away_score is not None
                        else None
                    ),

                    "home_winner": home_winner,

                    "status": status_data.get(
                        "abstractGameState"
                    ),

                    "detailed_status": status_data.get(
                        "detailedState"
                    ),

                    "venue": venue,

                    "updated_at": (
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                    ),
                }
            )

    return games


def save_games(games):
    """
    Guarda o actualiza partidos en Supabase.
    """

    if not games:
        return 0

    supabase = get_supabase_client()

    response = (
        supabase
        .table("mlb_game_history")
        .upsert(
            games,
            on_conflict="game_id"
        )
        .execute()
    )

    return len(
        response.data or []
    )


def sync_historical_games(days=30):
    """
    Sincroniza los últimos N días de MLB.
    """

    today = datetime.now(
        timezone.utc
    ).date()

    start_date = (
        today - timedelta(
            days=days
        )
    )

    start_date_str = start_date.isoformat()
    end_date_str = today.isoformat()

    print(
        "===================================="
    )

    print(
        " SPORTS PREDICTOR - MLB HISTORY"
    )

    print(
        "===================================="
    )

    print(
        f"Periodo: {start_date_str} "
        f"hasta {end_date_str}"
    )

    data = get_schedule(
        start_date=start_date_str,
        end_date=end_date_str,
    )

    games = extract_games(
        data
    )

    print(
        f"Partidos encontrados: {len(games)}"
    )

    final_games = [
        game
        for game in games
        if game.get("status") == "Final"
    ]

    print(
        f"Partidos Final encontrados: "
        f"{len(final_games)}"
    )

    saved = save_games(
        final_games
    )

    print(
        f"Partidos guardados/actualizados: "
        f"{saved}"
    )

    print(
        "===================================="
    )

    return {
        "success": True,
        "found": len(games),
        "final": len(final_games),
        "saved": saved,
        "start_date": start_date_str,
        "end_date": end_date_str,
    }


if __name__ == "__main__":

    sync_historical_games(
        days=30
          )
