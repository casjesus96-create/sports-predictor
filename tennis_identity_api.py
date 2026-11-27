"""Manual, confirmation-based ATP/WTA player identity resolution."""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from repository import get_supabase_client
from tennis_archive import SUPPORTED_LEAGUES, normalize_player_name

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tennis/identity", tags=["Tennis identity"])
PLAYERS_VIEW = "tennis_archive_players"
ALIASES_TABLE = "tennis_player_aliases"


class PlayerAliasRequest(BaseModel):
    league: str = Field(min_length=3, max_length=3)
    alias_name: str = Field(min_length=2, max_length=120)
    player_id: str = Field(min_length=1, max_length=40)


def _league(value: str) -> str:
    selected = str(value or "").strip().upper()
    if selected not in SUPPORTED_LEAGUES:
        raise HTTPException(status_code=400, detail="league debe ser ATP o WTA.")
    return selected


def _search_tokens(value: str) -> list[str]:
    normalized = normalize_player_name(value)
    return [token for token in normalized.split() if len(token) >= 3]


@router.get("/players")
def search_archive_players(
    league: str = Query(..., pattern="^(?i:ATP|WTA)$"),
    query: str = Query(..., min_length=2, max_length=120),
):
    """Return exact archive players sharing one or more normalized name tokens.

    Token overlap is candidate discovery only. It never resolves or merges identities.
    """
    selected = _league(league)
    tokens = _search_tokens(query)
    if not tokens:
        raise HTTPException(status_code=400, detail="Escribe al menos tres caracteres válidos.")
    client = get_supabase_client()
    candidates: dict[str, dict[str, Any]] = {}
    try:
        for token in tokens[:8]:
            rows = client.table(PLAYERS_VIEW).select(
                "league,player_id,player_name,player_name_key,matches,first_match,latest_match"
            ).eq("league", selected).ilike(
                "player_name", f"%{token}%"
            ).order("matches", desc=True).limit(50).execute().data or []
            for row in rows:
                player_id = str(row.get("player_id") or "").strip()
                if not player_id:
                    continue
                candidate = candidates.setdefault(player_id, {
                    "league": selected,
                    "player_id": player_id,
                    "player_name": str(row.get("player_name") or ""),
                    "player_name_key": str(row.get("player_name_key") or ""),
                    "matches": int(row.get("matches") or 0),
                    "first_match": row.get("first_match"),
                    "latest_match": row.get("latest_match"),
                    "matched_terms": [],
                })
                candidate["matched_terms"].append(token)
    except Exception as exc:
        logger.exception("Could not search the tennis player archive")
        raise HTTPException(status_code=503, detail="No se pudo consultar el catálogo ATP/WTA.") from exc

    result = sorted(
        candidates.values(),
        key=lambda item: (-len(set(item["matched_terms"])), -item["matches"], item["player_name"].casefold()),
    )
    for item in result:
        item["matched_terms"] = sorted(set(item["matched_terms"]))
    return {
        "success": True,
        "league": selected,
        "query": query,
        "candidates": result[:30],
        "count": len(result[:30]),
        "automatic_match": False,
        "writes": 0,
        "provider_calls": 0,
    }


@router.post("/aliases")
def confirm_player_alias(payload: PlayerAliasRequest):
    """Persist a player-name alias only after explicit selection of an archive ID."""
    selected = _league(payload.league)
    alias_name = str(payload.alias_name or "").strip()
    alias_key = normalize_player_name(alias_name)
    player_id = str(payload.player_id or "").strip()
    if len(alias_name) < 2 or len(alias_name) > 120 or not alias_key or not player_id:
        raise HTTPException(status_code=422, detail="Alias y jugador canónico son obligatorios.")

    client = get_supabase_client()
    try:
        target_rows = client.table(PLAYERS_VIEW).select(
            "player_id,player_name,player_name_key"
        ).eq("league", selected).eq("player_id", player_id).limit(2).execute().data or []
        if len(target_rows) != 1:
            raise HTTPException(status_code=404, detail="El ID elegido no existe de forma única en el archivo de esta categoría.")
        target = target_rows[0]
        canonical_name = str(target.get("player_name") or "").strip()
        canonical_key = str(target.get("player_name_key") or normalize_player_name(canonical_name))
        if alias_key == canonical_key:
            return {
                "success": True, "created": False, "already_canonical": True,
                "league": selected, "alias": alias_name, "player_id": player_id,
                "canonical_name": canonical_name,
            }

        # Never let an alias shadow a different player's canonical archive name.
        canonical_conflicts = client.table(PLAYERS_VIEW).select(
            "player_id,player_name"
        ).eq("league", selected).eq("player_name_key", alias_key).limit(3).execute().data or []
        if any(str(row.get("player_id")) != player_id for row in canonical_conflicts):
            raise HTTPException(status_code=409, detail="Este nombre ya corresponde a otra identidad canónica del archivo.")

        existing = client.table(ALIASES_TABLE).select(
            "player_id"
        ).eq("league", selected).eq("alias_key", alias_key).limit(2).execute().data or []
        if existing:
            if len(existing) == 1 and str(existing[0].get("player_id")) == player_id:
                return {
                    "success": True, "created": False, "already_confirmed": True,
                    "league": selected, "alias": alias_name, "player_id": player_id,
                    "canonical_name": canonical_name,
                }
            raise HTTPException(status_code=409, detail="Este nombre ya está asociado a otra jugadora o jugador. No se modificó la asociación existente.")

        client.table(ALIASES_TABLE).insert({
            "league": selected,
            "alias_key": alias_key,
            "alias_name": alias_name,
            "player_id": player_id,
            "canonical_name": canonical_name,
            "created_by": "manual_user_confirmation",
        }).execute()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not persist confirmed tennis player alias")
        raise HTTPException(status_code=503, detail="No se pudo guardar la equivalencia confirmada.") from exc

    return {
        "success": True, "created": True, "league": selected,
        "alias": alias_name, "alias_key": alias_key, "player_id": player_id,
        "canonical_name": canonical_name, "scope": "league",
    }
