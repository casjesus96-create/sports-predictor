"""Cross-sport best-play recommendations based only on saved official forecasts.

Only moneyline / match-winner markets are supported in this first release.
No player props, quarter totals, spreads, or score projections are fabricated.
Automatic odds require ODDS_API_KEY (The Odds API); manual odds are a separate
immutable observation and never overwrite an existing recommendation.
"""
from __future__ import annotations

import logging
import math
import os
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Literal

import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from decision_engine import evaluate_decision
from repository import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/best-plays", tags=["Centro de Mejores Jugadas"])
UTC = timezone.utc
ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports"
ODDS_SPORT_KEYS = {"MLB": "baseball_mlb", "NBA": "basketball_nba", "NFL": "americanfootball_nfl"}
OFFICIAL_MODELS = {"MLB": "2.0.0-matchup", "NBA": "NBA-1.1.0", "NFL": "NFL-1.0.0"}


class ManualRecommendationRequest(BaseModel):
    prediction_snapshot_id: str = Field(min_length=1, max_length=100)
    selected_side: Literal["home", "away"]
    decimal_odds: float = Field(gt=1, le=1000)
    bookmaker: str = Field(default="Entrada manual", min_length=1, max_length=120)


def _normalize(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _sport(row: dict) -> str:
    league = str(row.get("league") or "").strip().upper()
    raw = str(row.get("sport") or "").strip().upper()
    value = league or raw
    return {"BASEBALL": "MLB", "BASKETBALL": "NBA", "AMERICAN FOOTBALL": "NFL",
            "FOOTBALL": "NFL", "TENNIS": "TENNIS"}.get(value, value)


def _teams(row: dict) -> tuple[str, str]:
    features = row.get("features") or {}
    game = features.get("game") or {}
    home = game.get("home") or game.get("home_team") or game.get("homeTeam") or {}
    away = game.get("away") or game.get("away_team") or game.get("awayTeam") or {}
    if isinstance(home, dict):
        home = home.get("name") or home.get("full_name") or home.get("displayName") or home.get("abbreviation")
    if isinstance(away, dict):
        away = away.get("name") or away.get("full_name") or away.get("displayName") or away.get("abbreviation")
    return str(home or "").strip(), str(away or "").strip()


def _snapshot_date(row: dict) -> str | None:
    # "Analyzed that day" is based on the immutable snapshot's created_at.
    created = row.get("created_at")
    if not created:
        return None
    try:
        parsed = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).date().isoformat()
    except (TypeError, ValueError):
        return None


def _eligible_snapshot(row: dict) -> dict | None:
    sport = _sport(row)
    if sport not in OFFICIAL_MODELS or row.get("model_version") != OFFICIAL_MODELS[sport]:
        return None
    if str(row.get("result_status") or "").upper() != "PENDING":
        return None
    try:
        home_p, away_p = float(row.get("home_probability")), float(row.get("away_probability"))
        if not (math.isfinite(home_p) and math.isfinite(away_p) and 0 < home_p < 1 and 0 < away_p < 1):
            return None
        if abs(home_p + away_p - 1) > 0.03:
            return None
    except (TypeError, ValueError):
        return None
    home, away = _teams(row)
    if not home or not away:
        return None
    quality = row.get("data_quality")
    try:
        quality = max(0, min(100, int(float(quality)))) if quality is not None else None
    except (TypeError, ValueError):
        quality = None
    return {
        "prediction_snapshot_id": str(row.get("id")),
        "event_id": str(row.get("event_id") or ""),
        "sport": sport,
        "model_version": row.get("model_version"),
        "created_at": row.get("created_at"),
        "home": home, "away": away,
        "home_probability": home_p, "away_probability": away_p,
        "data_quality": quality,
    }


def _load_snapshots(day: str) -> list[dict]:
    response = (get_supabase_client().table("prediction_snapshots")
        .select("id,event_id,sport,league,model_version,created_at,result_status,home_probability,away_probability,data_quality,features")
        .eq("result_status", "PENDING").order("created_at", desc=True).limit(1000).execute())
    eligible = []
    for row in response.data or []:
        if _snapshot_date(row) != day:
            continue
        item = _eligible_snapshot(row)
        if item:
            eligible.append(item)
    return eligible


def _get_odds(sport: str) -> list[dict]:
    key = os.getenv("ODDS_API_KEY", "").strip()
    if not key:
        return []
    sport_key = ODDS_SPORT_KEYS.get(sport)
    if not sport_key:
        return []
    try:
        response = requests.get(
            f"{ODDS_API_BASE}/{sport_key}/odds",
            params={"apiKey": key, "regions": "us", "markets": "h2h", "oddsFormat": "decimal"},
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Automatic odds unavailable for %s: %s", sport, exc)
        return []


def _market_quote(event: dict, selected_team: str) -> dict | None:
    selected_key = _normalize(selected_team)
    outcomes_by_book = []
    for bookmaker in event.get("bookmakers") or []:
        market = next((m for m in bookmaker.get("markets") or [] if m.get("key") == "h2h"), None)
        if not market:
            continue
        outcomes = market.get("outcomes") or []
        selected = next((o for o in outcomes if _normalize(o.get("name")) == selected_key), None)
        other = next((o for o in outcomes if _normalize(o.get("name")) != selected_key), None)
        if selected and other:
            try:
                odds = float(selected.get("price"))
                other_odds = float(other.get("price"))
                if odds > 1 and other_odds > 1 and math.isfinite(odds) and math.isfinite(other_odds):
                    outcomes_by_book.append({"decimal_odds": odds, "opponent_decimal_odds": other_odds,
                        "bookmaker": bookmaker.get("title") or bookmaker.get("key") or "Proveedor automático",
                        "observed_at": market.get("last_update") or bookmaker.get("last_update")})
            except (TypeError, ValueError):
                continue
    return max(outcomes_by_book, key=lambda x: x["decimal_odds"]) if outcomes_by_book else None


def _ranking_score(ev_percent: float, probability: float, quality: int | None) -> float | None:
    # Balanced ranking: expected value 40%, probability 35%, data quality 25%.
    # Missing quality means no rank, rather than an invented quality score.
    if quality is None:
        return None
    ev_component = max(0.0, min(1.0, ev_percent / 20.0))
    return round(100 * (0.40 * ev_component + 0.35 * probability + 0.25 * (quality / 100)), 4)


def _create_recommendation(snapshot: dict, side: str, odds: float, odds_source: str,
                           bookmaker: str, observed_at: str | None,
                           opponent_odds: float | None = None) -> dict | None:
    probability = snapshot["home_probability"] if side == "home" else snapshot["away_probability"]
    selected_team = snapshot["home"] if side == "home" else snapshot["away"]
    opponent_team = snapshot["away"] if side == "home" else snapshot["home"]
    result = evaluate_decision(
        sport=snapshot["sport"], model_probability=probability, decimal_odds=odds,
        data_quality=snapshot["data_quality"], opponent_decimal_odds=opponent_odds,
    )
    ev = float(result["expected_value_percent"])
    score = _ranking_score(ev, probability, snapshot["data_quality"])
    # Positive EV alone is not sufficient: require the same quality gate as the decision engine.
    if ev <= 0 or snapshot["data_quality"] is None or snapshot["data_quality"] < 50:
        return None
    return {
        "prediction_snapshot_id": snapshot["prediction_snapshot_id"],
        "event_id": snapshot["event_id"], "sport": snapshot["sport"],
        "model_version": snapshot["model_version"], "selected_side": side,
        "selected_team": selected_team, "opponent_team": opponent_team,
        "market_key": "h2h", "market_label": "Ganador del partido",
        "model_probability": probability, "decimal_odds": odds,
        "fair_odds": result["fair_odds"], "implied_probability": result["implied_probability"],
        "edge_percentage_points": result["edge_percentage_points"],
        "expected_value_percent": ev, "data_quality": snapshot["data_quality"],
        "ranking_score": score, "classification": result["classification"],
        "odds_source": odds_source, "bookmaker": bookmaker,
        "odds_observed_at": observed_at, "model_snapshot_created_at": snapshot["created_at"],
        "recommendation_payload": {"evaluation": result, "ranking_method": "balanced-v1",
            "odds_source": odds_source, "bookmaker": bookmaker, "odds_observed_at": observed_at},
    }


def _save_immutable(payload: dict) -> dict:
    response = get_supabase_client().table("best_play_recommendations").insert(payload).execute()
    rows = response.data or []
    if not rows:
        raise RuntimeError("Supabase no devolvió la recomendación guardada.")
    return rows[0]


@router.get("/status")
def best_plays_status():
    return {
        "success": True, "automatic_odds_configured": bool(os.getenv("ODDS_API_KEY", "").strip()),
        "automatic_provider": "The Odds API" if os.getenv("ODDS_API_KEY", "").strip() else None,
        "manual_fallback": True, "ranking": "balanced-v1",
        "supported_recommendation_markets": ["h2h"],
        "supported_official_models": OFFICIAL_MODELS,
        "unsupported_sports_note": "Tenis y fútbol no se recomiendan todavía: sus predicciones usan almacenes/modelos separados y no están declaradas aquí como modelos oficiales activos.",
    }


@router.get("/candidates")
def best_play_candidates(day: str = Query(default=None, alias="date")):
    selected_day = day or datetime.now(UTC).date().isoformat()
    try:
        date.fromisoformat(selected_day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date debe tener formato YYYY-MM-DD.") from exc
    try:
        rows = _load_snapshots(selected_day)
        return {"success": True, "date": selected_day, "total": len(rows),
            "automatic_odds_configured": bool(os.getenv("ODDS_API_KEY", "").strip()),
            "candidates": rows}
    except Exception as exc:
        logger.exception("Could not load official snapshots for Best Plays")
        raise HTTPException(status_code=503, detail="No fue posible consultar snapshots oficiales. Verifica Supabase.") from exc


@router.post("/generate")
def generate_best_plays(day: str = Query(default=None, alias="date")):
    selected_day = day or datetime.now(UTC).date().isoformat()
    try:
        date.fromisoformat(selected_day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date debe tener formato YYYY-MM-DD.") from exc
    try:
        snapshots = _load_snapshots(selected_day)
        by_sport: dict[str, list[dict]] = {}
        for snapshot in snapshots:
            by_sport.setdefault(snapshot["sport"], []).append(snapshot)
        saved, skipped = [], []
        if not os.getenv("ODDS_API_KEY", "").strip():
            return {"success": True, "date": selected_day, "automatic_odds_configured": False,
                "saved": 0, "recommendations": [], "skipped": len(snapshots),
                "message": "Falta ODDS_API_KEY. Introduce cuotas manuales; no se generaron cuotas ni recomendaciones ficticias."}
        for sport, games in by_sport.items():
            events = _get_odds(sport)
            for snapshot in games:
                matched = next((e for e in events
                    if _normalize(e.get("home_team")) == _normalize(snapshot["home"])
                    and _normalize(e.get("away_team")) == _normalize(snapshot["away"])), None)
                if not matched:
                    skipped.append({"event_id": snapshot["event_id"], "sport": sport,
                        "game": f'{snapshot["away"]} vs {snapshot["home"]}', "reason": "No se encontró coincidencia exacta en el proveedor de cuotas."})
                    continue
                for side in ("home", "away"):
                    team = snapshot["home"] if side == "home" else snapshot["away"]
                    quote = _market_quote(matched, team)
                    if not quote:
                        continue
                    payload = _create_recommendation(snapshot, side, quote["decimal_odds"], "automatic",
                        quote["bookmaker"], quote.get("observed_at"), quote.get("opponent_decimal_odds"))
                    if payload:
                        saved.append(_save_immutable(payload))
        saved.sort(key=lambda r: float(r.get("ranking_score") or 0), reverse=True)
        return {"success": True, "date": selected_day, "automatic_odds_configured": True,
            "saved": len(saved), "recommendations": saved, "skipped": len(skipped), "skipped_details": skipped,
            "message": "Solo se guardaron selecciones con cuota obtenida, valor esperado positivo y calidad de datos suficiente."}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not generate Best Plays")
        raise HTTPException(status_code=503, detail="No fue posible generar y guardar recomendaciones. Comprueba la migración SQL y la conexión Supabase.") from exc


@router.post("/manual")
def create_manual_best_play(request: ManualRecommendationRequest):
    try:
        response = (get_supabase_client().table("prediction_snapshots")
            .select("id,event_id,sport,league,model_version,created_at,result_status,home_probability,away_probability,data_quality,features")
            .eq("id", request.prediction_snapshot_id).limit(1).execute())
        rows = response.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="No se encontró el snapshot de predicción.")
        snapshot = _eligible_snapshot(rows[0])
        if not snapshot:
            raise HTTPException(status_code=409, detail="Solo se aceptan snapshots pendientes de un modelo oficial activo con probabilidades válidas.")
        if _snapshot_date(rows[0]) != datetime.now(UTC).date().isoformat():
            raise HTTPException(status_code=409, detail="Solo puedes recomendar partidos analizados hoy (UTC).")
        side = request.selected_side
        selected_team = snapshot["home"] if side == "home" else snapshot["away"]
        payload = _create_recommendation(snapshot, side, request.decimal_odds, "manual",
            request.bookmaker.strip(), datetime.now(UTC).isoformat())
        if not payload:
            return {"success": True, "saved": False, "recommendation": None,
                "message": "No se guardó: el valor esperado no es positivo o la calidad de datos es inferior a 50/100."}
        row = _save_immutable(payload)
        return {"success": True, "saved": True, "recommendation": row,
            "message": "Recomendación manual guardada como snapshot inmutable; no modifica la predicción original ni otras recomendaciones."}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not save manual Best Play")
        raise HTTPException(status_code=503, detail="No se pudo guardar la recomendación manual. Comprueba la migración SQL y Supabase.") from exc


@router.get("/history")
def best_plays_history(day: str = Query(default=None, alias="date"), limit: int = Query(100, ge=1, le=500)):
    selected_day = day or datetime.now(UTC).date().isoformat()
    try:
        date.fromisoformat(selected_day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date debe tener formato YYYY-MM-DD.") from exc
    try:
        response = (get_supabase_client().table("best_play_recommendations").select("*")
            .gte("created_at", f"{selected_day}T00:00:00+00:00")
            .lt("created_at", f"{selected_day}T00:00:00+00:00")
            .order("ranking_score", desc=True).limit(limit).execute())
        return {"success": True, "date": selected_day, "total": len(response.data or []),
            "recommendations": response.data or []}
    except Exception as exc:
        logger.exception("Could not load Best Plays history")
        raise HTTPException(status_code=503, detail="No fue posible consultar el historial de recomendaciones.") from exc
