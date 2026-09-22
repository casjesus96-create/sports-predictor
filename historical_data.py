import time
from datetime import date, datetime, timedelta, timezone

import requests

from repository import get_supabase_client


MLB_API = "https://statsapi.mlb.com/api/v1"
SPORT_ID = 1
SEASON = 2026


def _get_json(url, params=None, timeout=30):
    response = requests.get(
        url,
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _extract_games(schedule_data):
    games = []

    for schedule_date in schedule_data.get("dates", []):
        games.extend(schedule_date.get("games", []))

    return games


def _get_schedule_range(start_date, end_date):
    data = _get_json(
        f"{MLB_API}/schedule",
        params={
            "sportId": SPORT_ID,
            "startDate": start_date,
            "endDate": end_date,
            "gameTypes": "R",
            "hydrate": "team,venue",
        },
    )

    return _extract_games(data)


def _get_game_details(game_id):
    data = _get_json(
        f"{MLB_API}/schedule",
        params={
            "sportId": SPORT_ID,
            "gamePk": str(game_id),
            "hydrate": "team,venue",
        },
    )

    games = _extract_games(data)

    if not games:
        return None

    return games[0]


def _build_payload(game):
    game_id = game.get("gamePk")

    teams = game.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}

    home_team = home.get("team") or {}
    away_team = away.get("team") or {}

    home_score = home.get("score")
    away_score = away.get("score")

    status = (game.get("status") or {}).get("abstractGameState")
    detailed_status = (game.get("status") or {}).get("detailedState")

    home_winner = None

    if home.get("isWinner") is not None:
        home_winner = bool(home.get("isWinner"))
    elif (
        home_score is not None
        and away_score is not None
    ):
        home_winner = int(home_score) > int(away_score)

    venue = game.get("venue") or {}

    game_date = game.get("gameDate")

    return {
        "game_id": str(game_id),
        "game_date": game_date,
        "season": int(game.get("season") or SEASON),
        "home_team_id": home_team.get("id"),
        "home_team": home_team.get("name"),
        "away_team_id": away_team.get("id"),
        "away_team": away_team.get("name"),
        "home_score": home_score,
        "away_score": away_score,
        "home_winner": home_winner,
        "status": status,
        "detailed_status": detailed_status,
        "venue": venue.get("name"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def sync_historical_games(
    start_date="2026-03-25",
    end_date=None,
    chunk_days=7,
    pause_seconds=0.15,
):
    """
    Sincroniza partidos MLB de temporada regular.

    Por defecto:
    - inicia el 25 de marzo de 2026
    - termina en la fecha actual UTC

    La consulta se realiza por bloques para evitar
    solicitar toda la temporada en una sola petición.
    """

    if end_date is None:
        end_date = datetime.now(
            timezone.utc
        ).date().isoformat()

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    if start > end:
        raise ValueError(
            "start_date no puede ser posterior a end_date"
        )

    supabase = get_supabase_client()

    total_games = 0
    inserted = 0
    updated = 0
    skipped = 0
    failed = 0

    current = start

    print("=" * 60)
    print("SINCRONIZACIÓN HISTÓRICA MLB")
    print("=" * 60)
    print(f"Temporada: {SEASON}")
    print(f"Desde: {start.isoformat()}")
    print(f"Hasta: {end.isoformat()}")
    print()

    while current <= end:
        chunk_end = min(
            current + timedelta(days=chunk_days - 1),
            end,
        )

        chunk_start_str = current.isoformat()
        chunk_end_str = chunk_end.isoformat()

        print(
            f"[RANGO] {chunk_start_str} -> "
            f"{chunk_end_str}"
        )

        try:
            games = _get_schedule_range(
                chunk_start_str,
                chunk_end_str,
            )

            print(
                f"[API] Partidos encontrados: "
                f"{len(games)}"
            )

            for game in games:
                total_games += 1

                try:
                    game_status = (
                        game.get("status") or {}
                    ).get("abstractGameState")

                    detailed_status = (
                        game.get("status") or {}
                    ).get("detailedState")

                    # Solo almacenamos partidos terminados.
                    if (
                        game_status != "Final"
                        and detailed_status != "Final"
                    ):
                        skipped += 1
                        continue

                    payload = _build_payload(game)

                    game_id = payload["game_id"]

                    if not game_id:
                        skipped += 1
                        continue

                    existing = (
                        supabase
                        .table("mlb_game_history")
                        .select("id")
                        .eq("game_id", game_id)
                        .limit(1)
                        .execute()
                    )

                    if existing.data:
                        (
                            supabase
                            .table("mlb_game_history")
                            .update(payload)
                            .eq(
                                "game_id",
                                game_id,
                            )
                            .execute()
                        )

                        updated += 1

                    else:
                        (
                            supabase
                            .table("mlb_game_history")
                            .insert(payload)
                            .execute()
                        )

                        inserted += 1

                except Exception as exc:
                    failed += 1

                    print(
                        f"[ERROR GAME] "
                        f"{game.get('gamePk')}: "
                        f"{exc}"
                    )

            time.sleep(pause_seconds)

        except Exception as exc:
            failed += 1

            print(
                f"[ERROR RANGO] "
                f"{chunk_start_str} -> "
                f"{chunk_end_str}: {exc}"
            )

        current = chunk_end + timedelta(days=1)

    print()
    print("=" * 60)
    print("SINCRONIZACIÓN FINALIZADA")
    print("=" * 60)
    print(f"Partidos procesados: {total_games}")
    print(f"Nuevos: {inserted}")
    print(f"Actualizados: {updated}")
    print(f"Omitidos: {skipped}")
    print(f"Errores: {failed}")

    return {
        "success": failed == 0,
        "season": SEASON,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "total_games": total_games,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
    }


if __name__ == "__main__":
    sync_historical_games()
