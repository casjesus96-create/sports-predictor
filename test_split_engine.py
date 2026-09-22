from datetime import datetime, timezone

from split_engine import (
    get_team_batting_splits,
    get_matchup_batting_splits,
)


YANKEES_ID = 147
RAYS_ID = 139

SEASON = 2026

HOME_PITCHER_HAND = "R"
AWAY_PITCHER_HAND = "R"


print("=" * 60)
print("PRUEBA SPLITS LHP/RHP")
print("=" * 60)

print()
print("YANKEES")
print("-" * 60)

try:
    yankees = get_team_batting_splits(
        team_id=YANKEES_ID,
        season=SEASON,
    )

    print("Vs RHP:")
    print(yankees["vs_right_handed"])

    print()
    print("Vs LHP:")
    print(yankees["vs_left_handed"])

except Exception as exc:
    print("ERROR YANKEES:", str(exc))


print()
print("=" * 60)
print("RAYS")
print("=" * 60)

try:
    rays = get_team_batting_splits(
        team_id=RAYS_ID,
        season=SEASON,
    )

    print("Vs RHP:")
    print(rays["vs_right_handed"])

    print()
    print("Vs LHP:")
    print(rays["vs_left_handed"])

except Exception as exc:
    print("ERROR RAYS:", str(exc))


print()
print("=" * 60)
print("PRUEBA DE MATCHUP")
print("=" * 60)

try:
    matchup = get_matchup_batting_splits(
        home_team_id=YANKEES_ID,
        away_team_id=RAYS_ID,
        home_pitcher_hand=HOME_PITCHER_HAND,
        away_pitcher_hand=AWAY_PITCHER_HAND,
        season=SEASON,
    )

    print()
    print("Yankees vs pitcher visitante:")
    print(
        matchup["home_team"]
    )

    print()
    print("Rays vs pitcher local:")
    print(
        matchup["away_team"]
    )

except Exception as exc:
    print("ERROR MATCHUP:", str(exc))


print()
print("=" * 60)
print("PRUEBA FINALIZADA")
print("=" * 60)

print(
    "Hora:",
    datetime.now(
        timezone.utc
    ).isoformat(),
)
