import tennis_api


def test_snapshot_lookup_returns_existing_immutable_snapshot(monkeypatch):
    snapshot = {
        "match_id": "match-1",
        "league": "ATP",
        "model_version": "TENNIS-ELO-1.0.0",
        "player1_probability": 0.65,
        "player2_probability": 0.35,
        "result_status": "PENDING",
    }
    captured = {}

    def fake_get_latest_snapshot(match_id, league):
        captured["match_id"] = match_id
        captured["league"] = league
        return snapshot

    monkeypatch.setattr(tennis_api, "get_latest_snapshot", fake_get_latest_snapshot)

    result = tennis_api.get_tennis_match_snapshot("match-1", "atp")

    assert result == {"success": True, "snapshot": snapshot}
    assert captured == {"match_id": "match-1", "league": "ATP"}


def test_snapshot_lookup_returns_null_when_no_pregame_snapshot_exists(monkeypatch):
    monkeypatch.setattr(tennis_api, "get_latest_snapshot", lambda match_id, league: None)

    result = tennis_api.get_tennis_match_snapshot("match-without-snapshot", "WTA")

    assert result == {"success": True, "snapshot": None}
