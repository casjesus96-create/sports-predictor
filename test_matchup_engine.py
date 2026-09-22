from datetime import datetime, timezone

from matchup_engine import get_matchup_data


GAME_ID = 823543

YANKEES_ID = 147
RAYS_ID = 139

BEFORE_DATE = "2026-09-22T00:00:00Z"

SEASON = 2026


print("=" * 70)
print("PRUEBA MATCHUP ENGINE")
print("=" * 70)

print()
print("GAME ID:", GAME_ID)
print("HOME TEAM: New York Yankees")
print("AWAY TEAM: Tampa Bay Rays")
print("BEFORE DATE:", BEFORE_DATE)
print("SEASON:", SEASON)

print()
print("-" * 70)
print("OBTENIENDO DATOS DEL MATCHUP")
print("-" * 70)

try:

    result = get_matchup_data(
        game_id=GAME_ID,
        home_team_id=YANKEES_ID,
        away_team_id=RAYS_ID,
        before_date=BEFORE_DATE,
        season=SEASON,
    )

    print()
    print("RESULTADO GENERAL:")
    print(result["available"])

    print()
    print("=" * 70)
    print("PITCHERS")
    print("=" * 70)

    print()
    print("Pitcher local:")
    print(result["pitchers"]["home"])

    print()
    print("Pitcher visitante:")
    print(result["pitchers"]["away"])

    print()
    print("=" * 70)
    print("MANOS")
    print("=" * 70)

    print()
    print(
        "Mano pitcher local:",
        result["pitcher_hands"]["home"],
    )

    print(
        "Mano pitcher visitante:",
        result["pitcher_hands"]["away"],
    )

    print()
    print("=" * 70)
    print("H2H")
    print("=" * 70)

    print(
        result["h2h"]
    )

    print()
    print("=" * 70)
    print("CONTEXTO GENERAL")
    print("=" * 70)

    print()
    print("Yankees:")
    print(
        result["general_context"]["home"]
    )

    print()
    print("Rays:")
    print(
        result["general_context"]["away"]
    )

    print()
    print("=" * 70)
    print("SPLITS OFENSIVOS DEL MATCHUP")
    print("=" * 70)

    home_split = (
        result["batting_splits"]
        ["home"]
        ["batting_split"]
    )

    away_split = (
        result["batting_splits"]
        ["away"]
        ["batting_split"]
    )

    print()
    print("YANKEES vs PITCHER VISITANTE")

    print(
        "Mano enfrentada:",
        result["batting_splits"]
        ["home"]
        ["pitcher_faced"],
    )

    print(
        "OPS:",
        home_split.get("ops"),
    )

    print(
        "AVG:",
        home_split.get("avg"),
    )

    print(
        "OBP:",
        home_split.get("obp"),
    )

    print(
        "SLG:",
        home_split.get("slg"),
    )

    print()
    print("RAYS vs PITCHER LOCAL")

    print(
        "Mano enfrentada:",
        result["batting_splits"]
        ["away"]
        ["pitcher_faced"],
    )

    print(
        "OPS:",
        away_split.get("ops"),
    )

    print(
        "AVG:",
        away_split.get("avg"),
    )

    print(
        "OBP:",
        away_split.get("obp"),
    )

    print(
        "SLG:",
        away_split.get("slg"),
    )

    print()
    print("=" * 70)
    print("PRUEBA FINALIZADA")
    print("=" * 70)

    print()
    print(
        "Hora:",
        datetime.now(
            timezone.utc
        ).isoformat(),
    )

except Exception as exc:

    print()
    print("=" * 70)
    print("ERROR")
    print("=" * 70)

    print(
        type(exc).__name__,
        ":",
        str(exc),
    )

    raise
