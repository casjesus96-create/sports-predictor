from datetime import datetime, timezone

from matchup_engine import (
    calculate_h2h,
    get_matchup_data,
)


# =========================================================
# CONFIGURACIÓN DE PRUEBA
# =========================================================

# Yankees
HOME_TEAM_ID = 147

# Rays
AWAY_TEAM_ID = 139

# Fecha del partido que estamos analizando.
#
# MUY IMPORTANTE:
# Todo lo utilizado por H2H debe ser anterior
# a esta fecha.
BEFORE_DATE = "2026-09-22T00:00:00Z"


# =========================================================
# PRUEBA H2H
# =========================================================

print("=" * 60)
print("PRUEBA H2H")
print("=" * 60)

try:

    h2h = calculate_h2h(
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        before_date=BEFORE_DATE,
        limit=10,
    )

    print(
        "Partidos H2H encontrados:",
        h2h["games"]
    )

    print(
        "Victorias Yankees:",
        h2h["home_team"]["wins"]
    )

    print(
        "Derrotas Yankees:",
        h2h["home_team"]["losses"]
    )

    print(
        "Win rate Yankees:",
        h2h["home_team"]["win_rate"]
    )

    print(
        "Victorias Rays:",
        h2h["away_team"]["wins"]
    )

    print(
        "Derrotas Rays:",
        h2h["away_team"]["losses"]
    )

    print(
        "Win rate Rays:",
        h2h["away_team"]["win_rate"]
    )

    print(
        "Carreras Yankees:",
        h2h["home_team"]["runs_scored"]
    )

    print(
        "Carreras Rays:",
        h2h["away_team"]["runs_scored"]
    )

    print(
        "Diferencia de carreras Yankees:",
        h2h["run_differential"]["home"]
    )

    print(
        "Diferencia de carreras Rays:",
        h2h["run_differential"]["away"]
    )

except Exception as exc:

    print(
        "ERROR H2H:",
        str(exc)
    )


# =========================================================
# PRUEBA MATCHUP COMPLETO
# =========================================================

print()
print("=" * 60)
print("PRUEBA MATCHUP")
print("=" * 60)

try:

    matchup = get_matchup_data(
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        before_date=BEFORE_DATE,
        pitcher_hand_home="R",
        pitcher_hand_away="R",
    )

    print()

    print(
        "H2H:",
        matchup["h2h"]
    )

    print()

    print(
        "Matchup de pitchers:"
    )

    print(
        matchup["pitcher_matchup"]
    )

except Exception as exc:

    print(
        "ERROR MATCHUP:",
        str(exc)
    )


# =========================================================
# FIN
# =========================================================

print()
print("=" * 60)
print("PRUEBA FINALIZADA")
print("=" * 60)
print(
    "Fecha límite utilizada:",
    BEFORE_DATE
)
print(
    "Hora de ejecución:",
    datetime.now(
        timezone.utc
    ).isoformat()
)
