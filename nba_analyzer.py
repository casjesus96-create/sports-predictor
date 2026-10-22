"""Análisis pregame NBA con resultados históricos y estadísticas recientes de boxscore."""
from datetime import datetime, timezone

from nba_client import get_game, get_team_histories, get_team_boxscore_histories
from nba_player_projections import project_players_from_recent_games
from nba_player_impact import evaluate_player_impact
from nba_prediction import MODEL_VERSION, predict_winner

UTC = timezone.utc
STAT_KEYS = (
    "rebounds", "offensive_rebounds", "defensive_rebounds", "assists",
    "steals", "blocks", "turnovers", "fouls", "field_goal_pct",
    "three_point_pct", "free_throw_pct",
)


def _team_metrics(team_id, games, boxscore_games=None):
    wins = losses = 0
    points_for = points_against = 0.0
    detail = []
    for game in games:
        home = str(game.get("home_team_id")) == str(team_id)
        team_points = game["home_score"] if home else game["away_score"]
        opponent_points = game["away_score"] if home else game["home_score"]
        if team_points > opponent_points:
            wins += 1
        else:
            losses += 1
        points_for += team_points
        points_against += opponent_points
        detail.append({
            "game_id": game["game_id"],
            "kickoff": game["kickoff"],
            "point_diff": team_points - opponent_points,
            "points_for": team_points,
            "points_against": opponent_points,
        })
    count = wins + losses
    recent = detail[:5]
    recent_boxscores = list(boxscore_games or [])[:5]

    recent_stats = {}
    for key in STAT_KEYS:
        values = [
            item.get("stats", {}).get(key)
            for item in recent_boxscores
            if item.get("stats", {}).get(key) is not None
        ]
        recent_stats[key] = round(sum(values) / len(values), 2) if values else None

    return {
        "team_id": str(team_id),
        "games": count,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / count, 4) if count else 0.5,
        "points_for_per_game": round(points_for / count, 2) if count else None,
        "points_against_per_game": round(points_against / count, 2) if count else None,
        "point_diff_per_game": round((points_for - points_against) / count, 2) if count else 0.0,
        "recent_games": len(recent),
        "recent_points_for_per_game": round(sum(x["points_for"] for x in recent) / len(recent), 2) if recent else None,
        "recent_points_against_per_game": round(sum(x["points_against"] for x in recent) / len(recent), 2) if recent else None,
        "recent_win_rate": round(sum(x["point_diff"] > 0 for x in recent) / len(recent), 4) if recent else 0.5,
        "recent_point_diff_per_game": round(sum(x["point_diff"] for x in recent) / len(recent), 2) if recent else 0.0,
        "boxscore_games": len(recent_boxscores),
        "recent_stats_per_game": recent_stats,
        "games_detail": detail[:10],
    }


def _mean_or_none(values):
    usable = [value for value in values if isinstance(value, (int, float))]
    return round(sum(usable) / len(usable), 2) if usable else None


def _project_stat(home, away, key):
    """Estimación neutral a partir de promedios recientes de ambos equipos."""
    return _mean_or_none([
        (home.get("recent_stats_per_game") or {}).get(key),
        (away.get("recent_stats_per_game") or {}).get(key),
    ])


def _build_projections(game, home_history, away_history):
    home_points = _mean_or_none([
        home_history.get("recent_points_for_per_game"),
        away_history.get("recent_points_against_per_game"),
    ])
    away_points = _mean_or_none([
        away_history.get("recent_points_for_per_game"),
        home_history.get("recent_points_against_per_game"),
    ])
    stats = {
        key: _project_stat(home_history, away_history, key)
        for key in STAT_KEYS
    }
    return {
        "method": "Promedios de los últimos cinco partidos finalizados antes del inicio; no son garantías.",
        "sample_games_home": home_history.get("recent_games", 0),
        "sample_games_away": away_history.get("recent_games", 0),
        "home_points": home_points,
        "away_points": away_points,
        "total_points": round(home_points + away_points, 2) if home_points is not None and away_points is not None else None,
        "recent_average_stats": stats,
        "home_team_recent_stats": home_history.get("recent_stats_per_game") or {},
        "away_team_recent_stats": away_history.get("recent_stats_per_game") or {},
    }


def analyze_nba_game(game_id):
    game = get_game(game_id)
    if not game:
        return {"success": False, "sport": "NBA", "game_id": str(game_id), "message": "No se encontró el partido NBA."}
    kickoff_value = game.get("kickoff")
    try:
        kickoff = datetime.fromisoformat(str(kickoff_value).replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=UTC)
        kickoff = kickoff.astimezone(UTC)
    except (TypeError, ValueError):
        return {"success": False, "sport": "NBA", "game_id": str(game_id), "message": "No hay una hora de inicio válida; se bloquea el análisis por seguridad."}

    now = datetime.now(UTC)
    if kickoff <= now or game.get("completed") or game.get("status") in {"in", "post"}:
        return {
            "success": False, "sport": "NBA", "game_id": str(game_id),
            "message": "El partido ya comenzó o terminó. El modelo pregame no utiliza información posterior al inicio.",
            "status": game.get("status"),
        }
    if not game.get("home_team_id") or not game.get("away_team_id"):
        return {"success": False, "sport": "NBA", "game_id": str(game_id), "message": "Faltan identificadores de los equipos."}

    cutoff = kickoff.isoformat()
    histories = get_team_histories([game["home_team_id"], game["away_team_id"]], cutoff)
    # Estadísticas detalladas se consultan únicamente para partidos anteriores al corte pregame.
    boxscores = get_team_boxscore_histories(histories, max_games=5)
    home_id = str(game["home_team_id"])
    away_id = str(game["away_team_id"])
    home_history = _team_metrics(home_id, histories.get(home_id, []), boxscores.get(home_id, []))
    away_history = _team_metrics(away_id, histories.get(away_id, []), boxscores.get(away_id, []))
    prediction = predict_winner(home_history, away_history, game.get("neutral_site", False))
    total_samples = home_history["games"] + away_history["games"]
    generated_at = now.isoformat()
    projections = _build_projections(game, home_history, away_history)
    # Player projections use only completed boxscores before this game's kickoff.
    projections["player_projections"] = project_players_from_recent_games(histories, cutoff, max_games=5)
    # Shadow evaluation only: this signal must not modify NBA-1.1.0 probabilities.
    projections["player_impact_evaluation"] = evaluate_player_impact(
        projections["player_projections"], home_id, away_id
    )
    return {
        "success": True,
        "sport": "NBA",
        "league": "NBA",
        "model_version": MODEL_VERSION,
        "generated_at": generated_at,
        "data_cutoff": cutoff,
        "game": game,
        "prediction": {
            **prediction,
            "winner": game["home"] if prediction["winner"] == "HOME" else game["away"],
            "winner_side": prediction["winner"],
        },
        "projections": projections,
        "factors": {
            "home_history": home_history,
            "away_history": away_history,
            "neutral_site": game.get("neutral_site", False),
            "historical_games_used": total_samples,
            "home_advantage_used": not game.get("neutral_site", False),
            "recent_boxscores_used": home_history["boxscore_games"] + away_history["boxscore_games"],
        },
        "limitations": [
            "La proyección de puntos se basa en puntos anotados y permitidos recientemente.",
            "Rebotes, asistencias, bloqueos, robos, pérdidas y porcentajes son promedios de boxscores recientes cuando la fuente los proporciona.",
            "No se ponderan lesiones, quintetos confirmados, carga de minutos ni líneas de mercado.",
            "Las estimaciones son experimentales, no garantías; si ESPN no publica estadísticas para un juego, ese dato queda sin muestra.",
        ],
    }
