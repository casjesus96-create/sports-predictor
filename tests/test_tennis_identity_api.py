from fastapi import HTTPException
import pytest

import tennis_identity_api as identity


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, *_args, **_kwargs): return self
    def eq(self, key, value):
        self.filters.append((key, value))
        return self
    def ilike(self, key, value):
        self.filters.append((key, value))
        return self
    def order(self, *_args, **_kwargs): return self
    def limit(self, _count): return self
    def insert(self, payload):
        self.inserted = payload
        return self
    def execute(self):
        rows = self.rows
        for key, value in self.filters:
            if key == "league":
                rows = [row for row in rows if row.get(key) == value]
            elif key == "player_id":
                rows = [row for row in rows if row.get(key) == value]
            elif key == "player_name":
                token = value.strip("%").casefold()
                rows = [row for row in rows if token in str(row.get(key) or "").casefold()]
            elif key == "player_name_key":
                rows = [row for row in rows if row.get(key) == value]
            elif key == "alias_key":
                rows = [row for row in rows if row.get(key) == value]
        # Supabase creates a fresh query builder for each table(...).select(...).
        # Reset filters so this lightweight fake does not leak predicates across calls.
        self.filters = []
        return type("Result", (), {"data": rows})()


class Client:
    def __init__(self, tables):
        self.tables = tables
    def table(self, name):
        return self.tables[name]


def test_player_search_returns_candidates_without_auto_resolving(monkeypatch):
    players = [{
        "league": "WTA", "player_id": "13883",
        "player_name": "Guiomar Zuleta De Reales",
        "player_name_key": "guiomar zuleta de reales",
        "matches": 290, "first_match": "2021-05-02", "latest_match": "2026-11-24",
    }]
    client = Client({"tennis_archive_players": Query(players)})
    monkeypatch.setattr(identity, "get_supabase_client", lambda: client)

    result = identity.search_archive_players("WTA", "Guiomar Maristany Zuleta De Reales")

    assert result["automatic_match"] is False
    assert result["writes"] == 0
    assert result["count"] == 1
    assert result["candidates"][0]["player_id"] == "13883"
    assert result["candidates"][0]["player_name"] == "Guiomar Zuleta De Reales"


def test_confirm_alias_persists_only_after_explicit_player_id(monkeypatch):
    players = [{
        "league": "WTA", "player_id": "13883", "player_name": "Guiomar Zuleta De Reales",
        "player_name_key": "guiomar zuleta de reales",
    }]
    alias_table = Query([])
    client = Client({
        "tennis_archive_players": Query(players),
        "tennis_player_aliases": alias_table,
    })
    monkeypatch.setattr(identity, "get_supabase_client", lambda: client)

    result = identity.confirm_player_alias(identity.PlayerAliasRequest(
        league="WTA", alias_name="Guiomar Maristany Zuleta De Reales", player_id="13883"
    ))

    assert result["created"] is True
    assert alias_table.inserted["player_id"] == "13883"
    assert alias_table.inserted["alias_key"] == "guiomar maristany zuleta de reales"
    assert alias_table.inserted["canonical_name"] == "Guiomar Zuleta De Reales"


def test_alias_cannot_shadow_another_canonical_player(monkeypatch):
    players = [
        {"league": "WTA", "player_id": "13883", "player_name": "Guiomar Zuleta De Reales",
         "player_name_key": "guiomar zuleta de reales"},
        {"league": "WTA", "player_id": "999", "player_name": "Other Player",
         "player_name_key": "guiomar maristany zuleta de reales"},
    ]
    client = Client({
        "tennis_archive_players": Query(players),
        "tennis_player_aliases": Query([]),
    })
    monkeypatch.setattr(identity, "get_supabase_client", lambda: client)

    with pytest.raises(HTTPException) as exc:
        identity.confirm_player_alias(identity.PlayerAliasRequest(
            league="WTA", alias_name="Guiomar Maristany Zuleta De Reales", player_id="13883"
        ))
    assert exc.value.status_code == 409


def test_alias_conflict_is_never_overwritten(monkeypatch):
    players = [{
        "league": "WTA", "player_id": "13883", "player_name": "Guiomar Zuleta De Reales",
        "player_name_key": "guiomar zuleta de reales",
    }]
    client = Client({
        "tennis_archive_players": Query(players),
        "tennis_player_aliases": Query([{"league": "WTA", "alias_key": "guiomar maristany zuleta de reales", "player_id": "555"}]),
    })
    monkeypatch.setattr(identity, "get_supabase_client", lambda: client)

    with pytest.raises(HTTPException) as exc:
        identity.confirm_player_alias(identity.PlayerAliasRequest(
            league="WTA", alias_name="Guiomar Maristany Zuleta De Reales", player_id="13883"
        ))
    assert exc.value.status_code == 409
