from historical_data import get_json
from form_engine import get_matchup_form
from repository import get_supabase_client


def main():
    print("====================================")
    print(" SPORTS PREDICTOR - TEST FORM ENGINE")
    print("====================================")

    supabase = get_supabase_client()

    response = (
        supabase
        .table("mlb_game_history")
        .select(
            "game_id,"
            "game_date,"
            "home_team_id,"
            "home_team,"
            "away_team_id,"
            "away_team,"
            "home_score,"
            "away_score,"
            "status"
        )
        .eq("status", "Final")
        .order("game_date", desc=True)
        .limit(1)
        .execute()
    )

    games = response.data or []

    if not games:
        print("ERROR: No hay partidos históricos disponibles.")
        return

    game = games[0]

    print("")
    print("Partido utilizado para la prueba:")
    print(f"Game ID: {game['game_id']}")
    print(f"Fecha: {game['game_date']}")
    print(f"Local: {game['home_team']}")
    print(f"Visitante: {game['away_team']}")
    print(
        f"Resultado: "
        f"{game['home_score']} - {game['away_score']}"
    )

    print("")
    print("Calculando forma previa...")
    print("IMPORTANTE: el partido utilizado NO se incluirá")
    print("en los cálculos porque usamos game_date como corte.")

    form = get_matchup_form(
        home_team_id=game["home_team_id"],
        away_team_id=game["away_team_id"],
        before_date=game["game_date"],
    )

    print("")
    print("====================================")
    print(" FORMA DEL EQUIPO LOCAL")
    print("====================================")

    print("Últimos 5:")
    print(form["home"]["last_5"])

    print("")
    print("Últimos 10:")
    print(form["home"]["last_10"])

    print("")
    print("Últimos 15:")
    print(form["home"]["last_15"])

    print("")
    print("====================================")
    print(" FORMA DEL EQUIPO VISITANTE")
    print("====================================")

    print("Últimos 5:")
    print(form["away"]["last_5"])

    print("")
    print("Últimos 10:")
    print(form["away"]["last_10"])

    print("")
    print("Últimos 15:")
    print(form["away"]["last_15"])

    print("")
    print("====================================")
    print(" PRUEBA FINALIZADA")
    print("====================================")


if __name__ == "__main__":
    main()
