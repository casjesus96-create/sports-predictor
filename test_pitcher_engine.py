from datetime import datetime, timezone

from pitcher_engine import (
    get_game_pitchers,
    get_matchup_pitcher_hands,
)


GAME_ID = 823543


print("=" * 60)
print("PRUEBA PITCHER ENGINE")
print("=" * 60)

print()
print("GAME ID:", GAME_ID)

print()
print("-" * 60)
print("PITCHERS")
print("-" * 60)

try:
    result = get_game_pitchers(
        GAME_ID
    )

    print("Pitcher local:")
    print(result["home_pitcher"])

    print()
    print("Pitcher visitante:")
    print(result["away_pitcher"])

except Exception as exc:
    print("ERROR PITCHERS:", str(exc))


print()
print("=" * 60)
print("MANOS DEL MATCHUP")
print("=" * 60)

try:
    matchup = get_matchup_pitcher_hands(
        GAME_ID
    )

    print()
    print(
        "Mano pitcher local:",
        matchup["home_pitcher_hand"],
    )

    print(
        "Mano pitcher visitante:",
        matchup["away_pitcher_hand"],
    )

    print()
    print("Datos completos:")
    print(matchup)

except Exception as exc:
    print("ERROR MATCHUP:", str(exc))


print()
print("=" * 60)
print("PRUEBA FINALIZADA")
print("=" * 60)

print(
    "Hora:",
    datetime.now(timezone.utc).isoformat(),
)
