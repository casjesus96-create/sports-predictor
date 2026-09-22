import requests
from datetime import datetime, timezone


MLB_API = "https://statsapi.mlb.com/api/v1"
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1"


def _get_json(url, params=None, timeout=30):
    """
    Realiza una petición GET a MLB Stats API
    y devuelve el JSON.
    """
    response = requests.get(
        url,
        params=params,
        timeout=timeout,
    )

    response.raise_for_status()

    return response.json()


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_hand(value):
    """
    Normaliza la mano del pitcher.

    MLB normalmente utiliza:
    R = Right
    L = Left
    """
    if value is None:
        return None

    value = str(value).strip().upper()

    if value in ("R", "RIGHT", "RIGHT-HANDED", "RIGHT HANDED"):
        return "R"

    if value in ("L", "LEFT", "LEFT-HANDED", "LEFT HANDED"):
        return "L"

    return None


def _extract_pitcher_hand(person_data):
    """
    Intenta obtener la mano de lanzamiento
    desde la información del jugador.
    """

    people = person_data.get("people") or []

    if not people:
        return None

    player = people[0]

    pitch_hand = (
        player.get("pitchHand")
        or {}
    )

    code = pitch_hand.get("code")

    normalized = _normalize_hand(code)

    if normalized:
        return normalized

    description = pitch_hand.get("description")

    return _normalize_hand(description)


def get_player(player_id):
    """
    Obtiene información básica de un jugador MLB.
    """

    player_id = _safe_int(player_id)

    if player_id is None:
        raise ValueError("player_id inválido.")

    url = f"{MLB_API}/people/{player_id}"

    data = _get_json(url)

    people = data.get("people") or []

    if not people:
        return None

    return people[0]


def get_pitcher_hand(player_id):
    """
    Obtiene únicamente la mano de lanzamiento
    de un pitcher.

    Retorna:
        R
        L
        None
    """

    player = get_player(player_id)

    if not player:
        return None

    pitch_hand = player.get("pitchHand") or {}

    code = pitch_hand.get("code")

    normalized = _normalize_hand(code)

    if normalized:
        return normalized

    description = pitch_hand.get("description")

    return _normalize_hand(description)


def get_game_feed(game_id):
    """
    Obtiene el feed completo del partido.
    """

    game_id = _safe_int(game_id)

    if game_id is None:
        raise ValueError("game_id inválido.")

    url = f"{MLB_GAME_API}/game/{game_id}/feed/live"

    return _get_json(url)


def _extract_probable_pitcher_from_boxscore(
    feed,
    team_side,
):
    """
    Busca el pitcher probable/abridor dentro
    de los datos disponibles del partido.

    team_side debe ser:
        home
        away
    """

    live_data = feed.get("liveData") or {}

    boxscore = live_data.get("boxscore") or {}

    teams = boxscore.get("teams") or {}

    team_data = teams.get(team_side) or {}

    pitchers = team_data.get("pitchers") or []

    if pitchers:
        return pitchers[0]

    return None


def _extract_pitcher_from_game_data(
    feed,
    team_side,
):
    """
    Busca información del pitcher probable
    en gameData probablePitchers.
    """

    game_data = feed.get("gameData") or {}

    probable_pitchers = (
        game_data.get("probablePitchers")
        or {}
    )

    pitcher = probable_pitchers.get(team_side)

    if pitcher:
        return pitcher

    return None


def get_probable_pitcher(
    game_id,
    team_side,
):
    """
    Obtiene el pitcher probable de un equipo
    para un partido.

    team_side:
        home
        away
    """

    if team_side not in ("home", "away"):
        raise ValueError(
            "team_side debe ser 'home' o 'away'."
        )

    feed = get_game_feed(game_id)

    pitcher = _extract_pitcher_from_game_data(
        feed,
        team_side,
    )

    source = "gameData.probablePitchers"

    if not pitcher:
        pitcher = _extract_probable_pitcher_from_boxscore(
            feed,
            team_side,
        )

        source = "liveData.boxscore"

    if not pitcher:
        return {
            "available": False,
            "game_id": int(game_id),
            "team_side": team_side,
            "pitcher_id": None,
            "pitcher_name": None,
            "pitcher_hand": None,
            "source": None,
            "reason": (
                "MLB Stats API no proporcionó "
                "un pitcher probable para este equipo."
            ),
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    pitcher_id = (
        pitcher.get("id")
        or pitcher.get("personId")
    )

    pitcher_id = _safe_int(pitcher_id)

    pitcher_name = (
        pitcher.get("fullName")
        or pitcher.get("name")
    )

    pitcher_hand = _normalize_hand(
        pitcher.get("pitchHand")
        if isinstance(pitcher.get("pitchHand"), str)
        else None
    )

    if pitcher_hand is None:
        pitch_hand_data = (
            pitcher.get("pitchHand")
            or {}
        )

        if isinstance(pitch_hand_data, dict):
            pitcher_hand = _normalize_hand(
                pitch_hand_data.get("code")
            )

            if pitcher_hand is None:
                pitcher_hand = _normalize_hand(
                    pitch_hand_data.get("description")
                )

    if pitcher_hand is None and pitcher_id:
        try:
            pitcher_hand = get_pitcher_hand(
                pitcher_id
            )
        except Exception:
            pitcher_hand = None

    if pitcher_name is None and pitcher_id:
        try:
            player = get_player(pitcher_id)

            if player:
                pitcher_name = (
                    player.get("fullName")
                    or player.get("name")
                )
        except Exception:
            pass

    return {
        "available": True,
        "game_id": int(game_id),
        "team_side": team_side,
        "pitcher_id": pitcher_id,
        "pitcher_name": pitcher_name,
        "pitcher_hand": pitcher_hand,
        "source": source,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def get_game_pitchers(game_id):
    """
    Obtiene los dos pitchers probables
    de un partido.
    """

    home_pitcher = get_probable_pitcher(
        game_id=game_id,
        team_side="home",
    )

    away_pitcher = get_probable_pitcher(
        game_id=game_id,
        team_side="away",
    )

    return {
        "game_id": int(game_id),
        "home_pitcher": home_pitcher,
        "away_pitcher": away_pitcher,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def get_matchup_pitcher_hands(game_id):
    """
    Devuelve únicamente las manos de los pitchers
    que intervienen en el matchup.

    Esto será utilizado posteriormente por
    split_engine.py.
    """

    pitchers = get_game_pitchers(
        game_id
    )

    home_pitcher = pitchers["home_pitcher"]
    away_pitcher = pitchers["away_pitcher"]

    return {
        "game_id": int(game_id),
        "home_pitcher_hand": (
            home_pitcher.get("pitcher_hand")
            if home_pitcher
            else None
        ),
        "away_pitcher_hand": (
            away_pitcher.get("pitcher_hand")
            if away_pitcher
            else None
        ),
        "home_pitcher": home_pitcher,
        "away_pitcher": away_pitcher,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }
