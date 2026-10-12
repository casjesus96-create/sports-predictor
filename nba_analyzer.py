"""Análisis pregame NBA. No usa el marcador del partido que se proyecta."""
from datetime import datetime, timezone

from nba_client import get_game, get_team_history
from nba_prediction import MODEL_VERSION, predict_winner

UTC = timezone.utc


def _team_metrics(team_id, cutoff):
    games = get_team_history(team_id, cutoff)
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
        "recent_win_rate": round(sum(x["point_diff"] > 0 for x in recent) / len(recent), 4) if recent else 0.5,
        "recent_point_diff_per_game": round(sum(x["point_diff"] for x in recent) / len(recent), 2) if recent else 0.0,
        "games_detail": detail[:10],
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
    home_history = _team_metrics(game["home_team_id"], cutoff)
    away_history = _team_metrics(game["away_team_id"], cutoff)
    prediction = predict_winner(home_history, away_history, game.get("neutral_site", False))
    total_samples = home_history["games"] + away_history["games"]
    generated_at = now.isoformat()
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
        "factors": {
            "home_history": home_history,
            "away_history": away_history,
            "neutral_site": game.get("neutral_site", False),
            "historical_games_used": total_samples,
            "home_advantage_used": not game.get("neutral_site", False),
        },
        "limitations": [
            "El modelo usa resultados históricos y forma reciente.",
            "No pondera lesiones, quintetos confirmados, carga de minutos ni líneas de mercado.",
            "Las probabilidades son estimaciones experimentales, no garantías.",
        ],
    }
