from prediction import analyze_game


# =========================================================
# CONFIGURACIÓN DE PRUEBA
# =========================================================

GAME_ID = 823543

HOME_TEAM_ID = 147
AWAY_TEAM_ID = 139

BEFORE_DATE = "2026-09-22T00:00:00Z"

SEASON = 2026


# =========================================================
# EJECUCIÓN
# =========================================================

print("=" * 70)
print("PRUEBA PREDICTION ENGINE")
print("=" * 70)

print()
print("GAME ID:", GAME_ID)
print("HOME TEAM ID:", HOME_TEAM_ID)
print("AWAY TEAM ID:", AWAY_TEAM_ID)
print("BEFORE DATE:", BEFORE_DATE)
print("SEASON:", SEASON)

print("-" * 70)
print("EJECUTANDO MODELO")
print("-" * 70)


try:

    result = analyze_game(
        game_id=GAME_ID,
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        before_date=BEFORE_DATE,
        season=SEASON,
    )

    print()
    print("RESULTADO GENERAL:")
    print(result.get("success"))

    print()
    print("=" * 70)
    print("PREDICCION")
    print("=" * 70)

    prediction = result.get(
        "prediction",
        {}
    )

    print(
        "LADO PROYECTADO:",
        prediction.get(
            "projected_side"
        )
    )

    print(
        "PROBABILIDAD HOME:",
        prediction.get(
            "home_probability"
        )
    )

    print(
        "PROBABILIDAD AWAY:",
        prediction.get(
            "away_probability"
        )
    )

    print(
        "CONFIANZA:",
        prediction.get(
            "confidence"
        )
    )

    print(
        "CALIDAD DE DATOS:",
        prediction.get(
            "data_quality"
        )
    )

    print()
    print("=" * 70)
    print("SEÑALES DEL MODELO")
    print("=" * 70)

    signals = result.get(
        "signals",
        {}
    )

    for key, value in signals.items():

        print(
            f"{key}: {value}"
        )

    print()
    print("=" * 70)
    print("PRUEBA FINALIZADA CORRECTAMENTE")
    print("=" * 70)

except Exception as exc:

    print()
    print("=" * 70)
    print("ERROR")
    print("=" * 70)

    print(
        type(exc).__name__,
        ":",
        str(exc)
    )

    raise
