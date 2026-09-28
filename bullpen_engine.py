import math
import requests
from datetime import datetime, timezone, timedelta

=========================================================

MLB API

=========================================================

MLB_API = "https://statsapi.mlb.com/api/v1"
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1"

MLB_HEADERS = {
"User-Agent": "Sports-Predictor/1.0",
"Accept": "application/json",
}

=========================================================

CONFIGURACIÓN

=========================================================

DEFAULT_SEASON = 2026

Ventanas utilizadas para medir carga reciente.

RECENT_DAYS_SHORT = 3
RECENT_DAYS_LONG = 5

Número máximo de partidos consultados por equipo.

MAX_HISTORY_GAMES = 20

Puntuación neutral cuando no existe información suficiente.

NEUTRAL_SCORE = 0.50

Límites de seguridad para el impacto posterior del factor.

IMPORTANTE:

Este archivo NO modifica directamente la probabilidad.

Estos valores quedan disponibles para la integración futura.

MAX_BULLPEN_IMPACT = 0.03

=========================================================

UTILIDADES

=========================================================

def _safe_int(value):
try:
return int(value)
except (TypeError, ValueError):
return None

def _safe_float(value):
try:
return float(value)
except (TypeError, ValueError):
return None

def _clamp(
value,
minimum=0.0,
maximum=1.0,
):
try:
value = float(value)
except (TypeError, ValueError):
return minimum

return max(
    minimum,
    min(maximum, value),
)

def _get_json(
url,
params=None,
timeout=20,
):
response = requests.get(
url,
params=params,
timeout=timeout,
headers=MLB_HEADERS,
)

response.raise_for_status()

return response.json()

def _parse_datetime(value):
"""
Convierte un datetime ISO de MLB a datetime UTC.

Devuelve None si el valor no puede interpretarse.
"""

if not value:
    return None

try:
    parsed = datetime.fromisoformat(
        str(value).replace(
            "Z",
            "+00:00",
        )
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )

except (
    TypeError,
    ValueError,
):
    return None

=========================================================

FECHA ACTUAL DEL PARTIDO

=========================================================

def _get_game_datetime(
game_id,
):
"""
Obtiene la fecha/hora programada del partido.
"""

game_id = _safe_int(game_id)

if game_id is None:
    return None

url = (
    f"{MLB_GAME_API}"
    f"/game/{game_id}/feed/live"
)

try:
    data = _get_json(url)

except Exception:
    return None

return (
    data
    .get("gameData", {})
    .get("datetime", {})
    .get("dateTime")
)

=========================================================

HISTORIAL MLB DEL EQUIPO

=========================================================

def get_team_schedule(
team_id,
start_date,
end_date,
season=DEFAULT_SEASON,
):
"""
Obtiene partidos del equipo dentro de una ventana temporal.

Se utiliza únicamente para determinar carga previa del bullpen.

No utiliza resultados posteriores al partido analizado.
"""

team_id = _safe_int(team_id)

if team_id is None:
    return []

params = {
    "sportId": 1,
    "teamId": team_id,
    "startDate": start_date,
    "endDate": end_date,
    "season": int(season),
}

url = f"{MLB_API}/schedule"

try:
    data = _get_json(
        url,
        params=params,
    )

except Exception:
    return []

games = []

for date_group in data.get("dates") or []:

    for game in (
        date_group.get("games") or []
    ):

        games.append(
            game
        )

return games

=========================================================

FEED DE UN PARTIDO

=========================================================

def get_game_feed(
game_id,
):
"""
Obtiene el feed completo de un partido.

Se utiliza para extraer información de pitchers
y carga del bullpen.
"""

game_id = _safe_int(game_id)

if game_id is None:
    return {}

url = (
    f"{MLB_GAME_API}"
    f"/game/{game_id}/feed/live"
)

try:
    return _get_json(
        url
    )

except Exception:
    return {}

=========================================================

IDENTIFICACIÓN DEL EQUIPO

=========================================================

def _team_was_home(
game,
team_id,
):
"""
Determina si el equipo analizado era local.
"""

team_id = _safe_int(team_id)

home_id = _safe_int(
    (
        game
        .get("teams", {})
        .get("home", {})
        .get("team", {})
        .get("id")
    )
)

return (
    home_id is not None
    and team_id == home_id
)

=========================================================

EXTRACCIÓN DE PITCHERS DEL BOX SCORE

=========================================================

def _get_pitcher_entries(
feed,
):
"""
Devuelve los pitchers utilizados en el partido.

La función intenta soportar las estructuras habituales
del Stats API sin asumir que todos los campos existen.
"""

live_data = feed.get(
    "liveData",
    {}
)

boxscore = live_data.get(
    "boxscore",
    {}
)

teams = boxscore.get(
    "teams",
    {}
)

result = {
    "home": [],
    "away": [],
}

for side in (
    "home",
    "away",
):

    team_data = (
        teams
        .get(side)
        or {}
    )

    pitchers = (
        team_data
        .get("pitchers")
        or []
    )

    players = (
        team_data
        .get("players")
        or {}
    )

    for pitcher_id in pitchers:

        pitcher_id = _safe_int(
            pitcher_id
        )

        if pitcher_id is None:
            continue

        player_key = (
            f"ID{pitcher_id}"
        )

        player = (
            players
            .get(player_key)
            or {}
        )

        stats = (
            player
            .get("stats", {})
            .get("pitching", {})
        )

        result[side].append(
            {
                "pitcher_id": pitcher_id,
                "stats": stats,
                "person": (
                    player
                    .get("person")
                    or {}
                ),
            }
        )

return result

=========================================================

CARGA DE UN PARTIDO

=========================================================

def calculate_game_bullpen_usage(
game_id,
team_id,
):
"""
Calcula la carga del bullpen de un equipo
en un partido concreto.

El pitcher abridor se excluye siempre que Stats API
permita identificarlo.

Métricas:

    innings
    batters_faced
    pitches
    strikeouts
    walks
    appearances

"""

feed = get_game_feed(
    game_id
)

if not feed:
    return {
        "available": False,
        "game_id": str(game_id),
        "team_id": team_id,
        "innings": 0.0,
        "pitches": 0,
        "batters_faced": 0,
        "strikeouts": 0,
        "walks": 0,
        "appearances": 0,
        "reason": "No se pudo obtener el feed.",
    }

game_data = feed.get(
    "gameData",
    {}
)

status = (
    game_data
    .get("status", {})
    .get("abstractGameState")
)

if status != "Final":
    return {
        "available": False,
        "game_id": str(game_id),
        "team_id": team_id,
        "innings": 0.0,
        "pitches": 0,
        "batters_faced": 0,
        "strikeouts": 0,
        "walks": 0,
        "appearances": 0,
        "reason": "El partido no está finalizado.",
    }

team_id = _safe_int(
    team_id
)

if team_id is None:
    return {
        "available": False,
        "game_id": str(game_id),
        "team_id": None,
        "innings": 0.0,
        "pitches": 0,
        "batters_faced": 0,
        "strikeouts": 0,
        "walks": 0,
        "appearances": 0,
        "reason": "team_id inválido.",
    }

side = (
    "home"
    if _team_was_home(
        game_data,
        team_id,
    )
    else "away"
)

pitchers = _get_pitcher_entries(
    feed
).get(side) or []

if not pitchers:
    return {
        "available": False,
        "game_id": str(game_id),
        "team_id": team_id,
        "innings": 0.0,
        "pitches": 0,
        "batters_faced": 0,
        "strikeouts": 0,
        "walks": 0,
        "appearances": 0,
        "reason": "No se encontraron pitchers.",
    }

innings = 0.0
pitches = 0
batters_faced = 0
strikeouts = 0
walks = 0
appearances = 0

starter_found = False

for index, pitcher in enumerate(
    pitchers
):

    stats = (
        pitcher
        .get("stats")
        or {}
    )

    innings_value = (
        _safe_float(
            stats.get("inningsPitched")
        )
    )

    pitches_value = (
        _safe_int(
            stats.get("numberOfPitches")
        )
    )

    batters_value = (
        _safe_int(
            stats.get("battersFaced")
        )
    )

    strikeouts_value = (
        _safe_int(
            stats.get("strikeOuts")
        )
    )

    walks_value = (
        _safe_int(
            stats.get("baseOnBalls")
        )
    )

    if innings_value is None:
        innings_value = 0.0

    if pitches_value is None:
        pitches_value = 0

    if batters_value is None:
        batters_value = 0

    if strikeouts_value is None:
        strikeouts_value = 0

    if walks_value is None:
        walks_value = 0

    # -------------------------------------------------
    # IDENTIFICACIÓN DEL ABRIDOR
    # -------------------------------------------------
    #
    # Stats API normalmente coloca al abridor
    # como primer pitcher utilizado.
    #
    # También comprobamos el campo isStarter
    # cuando está disponible.
    # -------------------------------------------------

    is_starter = (
        stats.get("isStarter")
    )

    if is_starter is True:
        starter_found = True
        continue

    if (
        not starter_found
        and index == 0
    ):
        starter_found = True
        continue

    # -------------------------------------------------
    # ACUMULAR BULLPEN
    # -------------------------------------------------

    innings += innings_value
    pitches += pitches_value
    batters_faced += batters_value
    strikeouts += strikeouts_value
    walks += walks_value
    appearances += 1

return {
    "available": appearances > 0,
    "game_id": str(game_id),
    "team_id": team_id,
    "innings": round(
        innings,
        3,
    ),
    "pitches": pitches,
    "batters_faced": batters_faced,
    "strikeouts": strikeouts,
    "walks": walks,
    "appearances": appearances,
}

=========================================================

CARGA HISTÓRICA DEL BULLPEN

=========================================================

def get_recent_bullpen_usage(
team_id,
before_datetime,
season=DEFAULT_SEASON,
days=3,
):
"""
Obtiene la carga del bullpen durante los días
inmediatamente anteriores al partido.

IMPORTANTE:

El partido objetivo queda fuera de la ventana.
"""

team_id = _safe_int(
    team_id
)

target_datetime = _parse_datetime(
    before_datetime
)

if (
    team_id is None
    or target_datetime is None
):
    return {
        "available": False,
        "games": [],
        "total_innings": 0.0,
        "total_pitches": 0,
        "total_batters_faced": 0,
        "total_strikeouts": 0,
        "total_walks": 0,
        "appearances": 0,
        "reason": "Fecha o team_id inválido.",
    }

start_datetime = (
    target_datetime
    - timedelta(days=days)
)

start_date = (
    start_datetime
    .date()
    .isoformat()
)

end_date = (
    target_datetime
    .date()
    .isoformat()
)

schedule = get_team_schedule(
    team_id=team_id,
    start_date=start_date,
    end_date=end_date,
    season=season,
)

games = []

total_innings = 0.0
total_pitches = 0
total_batters_faced = 0
total_strikeouts = 0
total_walks = 0
total_appearances = 0

for game in schedule:

    game_id = _safe_int(
        game.get("gamePk")
    )

    if game_id is None:
        continue

    game_datetime = _parse_datetime(
        game.get("gameDate")
    )

    if game_datetime is None:
        continue

    # Nunca utilizar partidos iguales o posteriores
    # al partido objetivo.
    if game_datetime >= target_datetime:
        continue

    game_status = (
        game
        .get("status", {})
        .get("abstractGameState")
    )

    if game_status != "Final":
        continue

    usage = calculate_game_bullpen_usage(
        game_id=game_id,
        team_id=team_id,
    )

    if not usage.get("available"):
        continue

    games.append(
        {
            "game_id": str(game_id),
            "game_date": game_datetime.isoformat(),
            "innings": usage["innings"],
            "pitches": usage["pitches"],
            "batters_faced": usage["batters_faced"],
            "strikeouts": usage["strikeouts"],
            "walks": usage["walks"],
            "appearances": usage["appearances"],
        }
    )

    total_innings += usage["innings"]
    total_pitches += usage["pitches"]
    total_batters_faced += usage["batters_faced"]
    total_strikeouts += usage["strikeouts"]
    total_walks += usage["walks"]
    total_appearances += usage["appearances"]

games = sorted(
    games,
    key=lambda item: item["game_date"],
    reverse=True,
)

return {
    "available": len(games) > 0,
    "days": days,
    "games": games,
    "games_count": len(games),
    "total_innings": round(
        total_innings,
        3,
    ),
    "total_pitches": total_pitches,
    "total_batters_faced": total_batters_faced,
    "total_strikeouts": total_strikeouts,
    "total_walks": total_walks,
    "appearances": total_appearances,
}

=========================================================

DÍAS DE DESCANSO

=========================================================

def calculate_rest_days(
team_id,
before_datetime,
season=DEFAULT_SEASON,
):
"""
Calcula cuántos días completos han transcurrido
desde el último partido finalizado del equipo.
"""

team_id = _safe_int(
    team_id
)

target_datetime = _parse_datetime(
    before_datetime
)

if (
    team_id is None
    or target_datetime is None
):
    return {
        "available": False,
        "rest_days": None,
    }

start_datetime = (
    target_datetime
    - timedelta(days=14)
)

schedule = get_team_schedule(
    team_id=team_id,
    start_date=start_datetime.date().isoformat(),
    end_date=target_datetime.date().isoformat(),
    season=season,
)

previous_games = []

for game in schedule:

    game_datetime = _parse_datetime(
        game.get("gameDate")
    )

    if game_datetime is None:
        continue

    if game_datetime >= target_datetime:
        continue

    status = (
        game
        .get("status", {})
        .get("abstractGameState")
    )

    if status != "Final":
        continue

    previous_games.append(
        game_datetime
    )

if not previous_games:
    return {
        "available": False,
        "rest_days": None,
    }

last_game = max(
    previous_games
)

elapsed_hours = (
    target_datetime - last_game
).total_seconds() / 3600.0

rest_days = max(
    0.0,
    elapsed_hours / 24.0 - 1.0,
)

return {
    "available": True,
    "rest_days": round(
        rest_days,
        2,
    ),
    "hours_since_last_game": round(
        elapsed_hours,
        2,
    ),
    "last_game_datetime":
        last_game.isoformat(),
}

=========================================================

COMPONENTE DE CARGA

=========================================================

def _calculate_load_score(
usage_3,
usage_5,
):
"""
Convierte la carga reciente en una puntuación
de disponibilidad.

1.00 = bullpen muy descansado
0.50 = neutral
0.00 = bullpen con carga muy alta

No utiliza ERA ni calidad de pitchers.
Solamente mide disponibilidad/carga.
"""

innings_3 = _safe_float(
    usage_3.get("total_innings")
) or 0.0

innings_5 = _safe_float(
    usage_5.get("total_innings")
) or 0.0

pitches_3 = _safe_float(
    usage_3.get("total_pitches")
) or 0.0

pitches_5 = _safe_float(
    usage_5.get("total_pitches")
) or 0.0

appearances_3 = _safe_float(
    usage_3.get("appearances")
) or 0.0

appearances_5 = _safe_float(
    usage_5.get("appearances")
) or 0.0

# -------------------------------------------------
# CARGA DE INNINGS
# -------------------------------------------------

innings_load = (
    innings_3 / 9.0 * 0.45
    + innings_5 / 15.0 * 0.25
)

# -------------------------------------------------
# CARGA DE LANZAMIENTOS
# -------------------------------------------------

pitch_load = (
    pitches_3 / 180.0 * 0.15
    + pitches_5 / 300.0 * 0.05
)

# -------------------------------------------------
# APARICIONES
# -------------------------------------------------

appearance_load = (
    appearances_3 / 6.0 * 0.07
    + appearances_5 / 10.0 * 0.03
)

total_load = (
    innings_load
    + pitch_load
    + appearance_load
)

total_load = _clamp(
    total_load,
    0.0,
    1.0,
)

availability = (
    1.0 - total_load
)

return round(
    _clamp(
        availability
    ),
    4,
)

=========================================================

AJUSTE POR DESCANSO

=========================================================

def _apply_rest_adjustment(
score,
rest_data,
):
"""
Ajusta ligeramente la disponibilidad según
el tiempo desde el último partido.

El ajuste es deliberadamente pequeño.
"""

if not rest_data.get(
    "available"
):
    return score

rest_days = _safe_float(
    rest_data.get(
        "rest_days"
    )
)

if rest_days is None:
    return score

if rest_days >= 2.0:
    adjustment = 0.04

elif rest_days >= 1.0:
    adjustment = 0.02

elif rest_days >= 0.0:
    adjustment = -0.03

else:
    adjustment = 0.0

return round(
    _clamp(
        score + adjustment
    ),
    4,
)

=========================================================

BULLPEN DE UN EQUIPO

=========================================================

def calculate_team_bullpen_status(
team_id,
before_datetime,
season=DEFAULT_SEASON,
):
"""
Construye el estado pregame del bullpen de un equipo.

Devuelve:

    usage_3_days
    usage_5_days
    rest
    availability_score
    confidence
"""

usage_3 = get_recent_bullpen_usage(
    team_id=team_id,
    before_datetime=before_datetime,
    season=season,
    days=RECENT_DAYS_SHORT,
)

usage_5 = get_recent_bullpen_usage(
    team_id=team_id,
    before_datetime=before_datetime,
    season=season,
    days=RECENT_DAYS_LONG,
)

rest = calculate_rest_days(
    team_id=team_id,
    before_datetime=before_datetime,
    season=season,
)

enough_data = (
    usage_3.get("available")
    or usage_5.get("available")
)

if not enough_data:
    return {
        "available": False,
        "team_id": team_id,
        "availability_score": None,
        "confidence": 0.0,
        "usage_3_days": usage_3,
        "usage_5_days": usage_5,
        "rest": rest,
        "reason": (
            "No existe suficiente historial "
            "para calcular la carga del bullpen."
        ),
    }

score = _calculate_load_score(
    usage_3,
    usage_5,
)

score = _apply_rest_adjustment(
    score,
    rest,
)

games_3 = usage_3.get(
    "games_count",
    0,
)

games_5 = usage_5.get(
    "games_count",
    0,
)

# -------------------------------------------------
# CONFIANZA DEL PROPIO INDICADOR
# -------------------------------------------------

if games_5 >= 4 and games_3 >= 2:
    confidence = 1.0

elif games_5 >= 3:
    confidence = 0.85

elif games_5 >= 2:
    confidence = 0.70

elif games_5 >= 1:
    confidence = 0.55

else:
    confidence = 0.0

return {
    "available": True,
    "team_id": team_id,

    "availability_score": score,

    "confidence": round(
        confidence,
        4,
    ),

    "usage_3_days": usage_3,

    "usage_5_days": usage_5,

    "rest": rest,

    "method": (
        "Bullpen workload based on recent "
        "innings, pitches, appearances and rest."
    ),
}

=========================================================

COMPARACIÓN DEL MATCHUP

=========================================================

def calculate_bullpen_matchup(
home_team_id,
away_team_id,
before_datetime,
season=DEFAULT_SEASON,
):
"""
Compara la disponibilidad del bullpen local
contra la del visitante.

IMPORTANTE:

Esta función NO modifica probabilidades.

Devuelve únicamente una señal normalizada para
que el modelo principal pueda utilizarla después
de una calibración.
"""

home = calculate_team_bullpen_status(
    team_id=home_team_id,
    before_datetime=before_datetime,
    season=season,
)

away = calculate_team_bullpen_status(
    team_id=away_team_id,
    before_datetime=before_datetime,
    season=season,
)

home_score = _safe_float(
    home.get(
        "availability_score"
    )
)

away_score = _safe_float(
    away.get(
        "availability_score"
    )
)

if (
    home_score is None
    or away_score is None
):

    return {
        "available": False,

        "home": home,

        "away": away,

        "difference": 0.0,

        "signal": 0.0,

        "confidence": 0.0,

        "max_recommended_impact":
            MAX_BULLPEN_IMPACT,

        "reason": (
            "No hay suficiente información "
            "para comparar ambos bullpens."
        ),
    }

difference = (
    home_score
    - away_score
)

# -------------------------------------------------
# SEÑAL NORMALIZADA
# -------------------------------------------------
#
# -1 = ventaja máxima visitante
#  0 = neutral
# +1 = ventaja máxima local
#
# Se utiliza tanh para evitar valores extremos.
# -------------------------------------------------

signal = math.tanh(
    difference * 3.0
)

home_confidence = _safe_float(
    home.get(
        "confidence"
    )
) or 0.0

away_confidence = _safe_float(
    away.get(
        "confidence"
    )
) or 0.0

confidence = (
    home_confidence
    * away_confidence
)

return {
    "available": True,

    "home": home,

    "away": away,

    "difference": round(
        difference,
        4,
    ),

    "signal": round(
        signal,
        4,
    ),

    "confidence": round(
        confidence,
        4,
    ),

    "max_recommended_impact":
        MAX_BULLPEN_IMPACT,

    "interpretation": (
        "positive = ventaja de disponibilidad "
        "del bullpen local; "
        "negative = ventaja del visitante."
    ),

    "generated_at":
        datetime.now(
            timezone.utc
        ).isoformat(),
}

=========================================================

FUNCIÓN PRINCIPAL

=========================================================

def get_bullpen_matchup_data(
home_team_id,
away_team_id,
before_datetime,
season=DEFAULT_SEASON,
):
"""
Punto de entrada principal para integrar el motor
con matchup_engine.py.

No altera probabilidades.
"""

try:

    return calculate_bullpen_matchup(
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        before_datetime=before_datetime,
        season=season,
    )

except Exception as exc:

    return {
        "available": False,

        "home": {
            "team_id": home_team_id,
            "availability_score": None,
            "confidence": 0.0,
        },

        "away": {
            "team_id": away_team_id,
            "availability_score": None,
            "confidence": 0.0,
        },

        "difference": 0.0,

        "signal": 0.0,

        "confidence": 0.0,

        "max_recommended_impact":
            MAX_BULLPEN_IMPACT,

        "error": str(exc),

        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }

=========================================================

EXPORTS

=========================================================

all = [
"get_bullpen_matchup_data",
"calculate_bullpen_matchup",
"calculate_team_bullpen_status",
"get_recent_bullpen_usage",
"calculate_rest_days",
"calculate_game_bullpen_usage",
]
