import requests
from datetime import datetime, timezone


MLB_API = "https://statsapi.mlb.com/api/v1"


def _get_json(url, params=None, timeout=30):
    response = requests.get(
        url,
        params=params,
        timeout=timeout,
    )

    response.raise_for_status()

    return response.json()


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _find_stat_split(data):
    """
    Extrae el primer split estadístico disponible
    de la respuesta de MLB Stats API.
    """

    stats = data.get("stats") or []

    for stat_group in stats:
        splits = stat_group.get("splits") or []

        if splits:
            return splits[0]

    return None


def get_team_batting_split(
    team_id,
    season=2026,
    pitcher_hand="R",
    game_type="R",
):
    """
    Obtiene el split ofensivo de un equipo
    contra pitchers derechos o izquierdos.

    pitcher_hand:
        R = pitcher derecho
        L = pitcher zurdo
    """

    pitcher_hand = str(
        pitcher_hand or "R"
    ).upper()

    if pitcher_hand not in ("R", "L"):
        raise ValueError(
            "pitcher_hand debe ser 'R' o 'L'"
        )

    # MLB Stats API utiliza:
    # vr = versus right-handed pitcher
    # vl = versus left-handed pitcher
    sit_code = (
        "vr"
        if pitcher_hand == "R"
        else "vl"
    )

    url = (
        f"{MLB_API}/teams/"
        f"{int(team_id)}/stats"
    )

    params = {
        "stats": "statSplits",
        "group": "hitting",
        "season": str(season),
        "gameType": game_type,
        "sitCodes": sit_code,
    }

    data = _get_json(
        url,
        params=params,
    )

    split = _find_stat_split(data)

    if not split:
        return {
            "available": False,
            "team_id": int(team_id),
            "season": int(season),
            "pitcher_hand": pitcher_hand,
            "sit_code": sit_code,
            "reason": (
                "MLB Stats API no devolvió "
                "un split ofensivo."
            ),
            "generated_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }

    stat = split.get("stat") or {}

    return {
        "available": True,
        "team_id": int(team_id),
        "season": int(season),
        "pitcher_hand": pitcher_hand,
        "sit_code": sit_code,

        "games": _safe_int(
            stat.get("gamesPlayed")
        ),

        "at_bats": _safe_int(
            stat.get("atBats")
        ),

        "runs": _safe_int(
            stat.get("runs")
        ),

        "hits": _safe_int(
            stat.get("hits")
        ),

        "doubles": _safe_int(
            stat.get("doubles")
        ),

        "triples": _safe_int(
            stat.get("triples")
        ),

        "home_runs": _safe_int(
            stat.get("homeRuns")
        ),

        "rbi": _safe_int(
            stat.get("rbi")
        ),

        "walks": _safe_int(
            stat.get("baseOnBalls")
        ),

        "strikeouts": _safe_int(
            stat.get("strikeOuts")
        ),

        "stolen_bases": _safe_int(
            stat.get("stolenBases")
        ),

        "avg": _safe_float(
            stat.get("avg")
        ),

        "obp": _safe_float(
            stat.get("obp")
        ),

        "slg": _safe_float(
            stat.get("slg")
        ),

        "ops": _safe_float(
            stat.get("ops")
        ),

        "total_bases": _safe_int(
            stat.get("totalBases")
        ),

        "left_on_base": _safe_int(
            stat.get("leftOnBase")
        ),

        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    }


def get_team_batting_splits(
    team_id,
    season=2026,
    game_type="R",
):
    """
    Obtiene simultáneamente los splits
    contra pitchers derechos e izquierdos.
    """

    vs_right = get_team_batting_split(
        team_id=team_id,
        season=season,
        pitcher_hand="R",
        game_type=game_type,
    )

    vs_left = get_team_batting_split(
        team_id=team_id,
        season=season,
        pitcher_hand="L",
        game_type=game_type,
    )

    return {
        "team_id": int(team_id),
        "season": int(season),
        "vs_right_handed": vs_right,
        "vs_left_handed": vs_left,
        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    }


def get_matchup_batting_splits(
    home_team_id,
    away_team_id,
    home_pitcher_hand,
    away_pitcher_hand,
    season=2026,
    game_type="R",
):
    """
    Calcula qué split ofensivo corresponde
    a cada equipo según la mano del pitcher
    rival.

    Home team enfrenta al pitcher visitante.
    Away team enfrenta al pitcher local.
    """

    home_pitcher_hand = str(
        home_pitcher_hand or "R"
    ).upper()

    away_pitcher_hand = str(
        away_pitcher_hand or "R"
    ).upper()

    home_vs_away_pitcher = (
        get_team_batting_split(
            team_id=home_team_id,
            season=season,
            pitcher_hand=away_pitcher_hand,
            game_type=game_type,
        )
    )

    away_vs_home_pitcher = (
        get_team_batting_split(
            team_id=away_team_id,
            season=season,
            pitcher_hand=home_pitcher_hand,
            game_type=game_type,
        )
    )

    return {
        "home_team": {
            "team_id": int(home_team_id),
            "pitcher_faced": away_pitcher_hand,
            "batting_split": home_vs_away_pitcher,
        },

        "away_team": {
            "team_id": int(away_team_id),
            "pitcher_faced": home_pitcher_hand,
            "batting_split": away_vs_home_pitcher,
        },

        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    }
