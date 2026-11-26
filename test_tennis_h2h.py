from datetime import date

import tennis_archive


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, _columns):
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def lt(self, key, value):
        self.filters.append(("lt", key, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _value):
        return self

    def execute(self):
        rows = self.rows
        for kind, key, value in self.filters:
            if kind == "eq":
                rows = [row for row in rows if str(row.get(key) or "") == str(value)]
            elif kind == "lt":
                rows = [row for row in rows if str(row.get(key) or "") < value]
        return FakeResponse(rows)


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _table):
        return FakeQuery(self.rows)


def _row(match_id, day, p1_id, p1_name, p2_id, p2_name, winner, surface, score):
    return {
        "source_match_id": match_id,
        "match_date": day,
        "tournament": "Test Open",
        "category": "Main tour",
        "surface": surface,
        "round_code": 3,
        "player1_id": p1_id,
        "player1_name": p1_name,
        "player1_name_key": tennis_archive.normalize_player_name(p1_name),
        "player2_id": p2_id,
        "player2_name": p2_name,
        "player2_name_key": tennis_archive.normalize_player_name(p2_name),
        "winner_id": winner,
        "score": score,
    }


def test_head_to_head_uses_exact_player_ids_and_returns_surface_breakdown(monkeypatch):
    rows = [
        _row("m1", "2024-06-01", "p1", "Player One", "p2", "Player Two", "p1", "Clay", "6-4 6-3"),
        _row("m2", "2025-01-10", "p2", "Player Two", "p1", "Player One", "p2", "Hard", "7-5 6-4"),
        _row("m3", "2026-02-01", "p1", "Player One", "p2", "Player Two", "p2", "Hard", "6-3 6-2"),
        _row("future", "2026-12-01", "p1", "Player One", "p2", "Player Two", "p1", "Grass", "6-0 6-0"),
    ]
    monkeypatch.setattr(tennis_archive, "get_supabase_client", lambda: FakeClient(rows))

    result = tennis_archive.get_head_to_head_archive(
        "Player One", "Player Two", "ATP", date(2026, 11, 1)
    )

    assert result["identity_resolved"] is True
    assert result["total_matches"] == 3
    assert result["player1_wins"] == 1
    assert result["player2_wins"] == 2
    assert {item["surface"]: item["matches"] for item in result["surface_breakdown"]} == {
        "Clay": 1, "Hard": 2
    }
    assert result["recent_matches"][0]["date"] == "2026-02-01"
    assert result["recent_matches"][0]["winner_name"] == "Player Two"


def test_head_to_head_does_not_merge_ambiguous_player_names(monkeypatch):
    rows = [
        _row("m1", "2025-01-10", "p1", "Player One", "p2", "Player Two", "p1", "Hard", "6-4 6-3"),
        _row("m2", "2025-02-10", "p9", "Player One", "p2", "Player Two", "p2", "Clay", "6-4 6-3"),
    ]
    monkeypatch.setattr(tennis_archive, "get_supabase_client", lambda: FakeClient(rows))

    result = tennis_archive.get_head_to_head_archive(
        "Player One", "Player Two", "ATP", date(2026, 1, 1)
    )

    assert result["identity_resolved"] is False
    assert result["identity_ambiguous"] is True
    assert result["total_matches"] == 0


def test_head_to_head_rejects_invalid_league_and_same_player():
    import pytest

    with pytest.raises(ValueError, match="ATP o WTA"):
        tennis_archive.get_head_to_head_archive(
            "Player One", "Player Two", "ITF", date(2026, 1, 1)
        )
    with pytest.raises(ValueError, match="dos nombres"):
        tennis_archive.get_head_to_head_archive(
            "Player One", "player-one", "ATP", date(2026, 1, 1)
        )
