"""Ensure the batch endpoint delegates final-game settlement to the shared integrity path."""

from types import SimpleNamespace

import pending_predictions


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def select(self, _fields):
        return self

    def eq(self, _key, _value):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return FakeQuery(self.rows)


class FakeHTTPResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "gameData": {
                "status": {
                    "abstractGameState": "Final",
                    "detailedState": "Final",
                },
                "teams": {
                    "home": {"name": "Home Team"},
                    "away": {"name": "Away Team"},
                },
            },
            "liveData": {
                "linescore": {
                    "teams": {
                        "home": {"runs": 5},
                        "away": {"runs": 2},
                    }
                }
            },
        }


def test_batch_endpoint_delegates_settlement_to_shared_repository(monkeypatch):
    record = {
        "id": "snapshot-123",
        "event_id": "game-123",
        "model_version": "2.0.0-matchup",
        "result_status": "PENDING",
        "features": {
            "game": {"home": "Home Team", "away": "Away Team"},
            "predicted_winner": "Home Team",
        },
        "home_probability": 0.65,
        "away_probability": 0.35,
        "confidence": 0.65,
    }
    monkeypatch.setattr(
        pending_predictions,
        "get_supabase_client",
        lambda: FakeSupabase([record]),
    )
    monkeypatch.setattr(
        pending_predictions.requests,
        "get",
        lambda *_args, **_kwargs: FakeHTTPResponse(),
    )
    calls = []

    def fake_settle_prediction(**kwargs):
        calls.append(kwargs)
        return {
            "updated": True,
            "predicted_winner": "Home Team",
            "prediction_result": "CORRECT",
        }

    monkeypatch.setattr(
        pending_predictions,
        "settle_prediction",
        fake_settle_prediction,
    )

    result = pending_predictions.settle_pending_predictions()

    assert result["success"] is True
    assert result["settled"] == 1
    assert calls == [{
        "event_id": "game-123",
        "actual_winner": "Home Team",
        "actual_home_score": 5,
        "actual_away_score": 2,
        "prediction_id": "snapshot-123",
        "model_version": "2.0.0-matchup",
    }]
    assert result["results"][0]["prediction_result"] == "CORRECT"


def test_batch_endpoint_leaves_record_pending_when_shared_settlement_rejects(monkeypatch):
    record = {
        "id": "snapshot-456",
        "event_id": "game-456",
        "model_version": "2.0.0-matchup",
        "result_status": "PENDING",
        "features": {"game": {"home": "Home Team", "away": "Away Team"}},
        "home_probability": None,
        "away_probability": None,
    }
    monkeypatch.setattr(
        pending_predictions,
        "get_supabase_client",
        lambda: FakeSupabase([record]),
    )
    monkeypatch.setattr(
        pending_predictions.requests,
        "get",
        lambda *_args, **_kwargs: FakeHTTPResponse(),
    )
    monkeypatch.setattr(
        pending_predictions,
        "settle_prediction",
        lambda **_kwargs: {
            "updated": False,
            "reason": "La predicción original no contiene datos suficientes.",
        },
    )

    result = pending_predictions.settle_pending_predictions()

    assert result["success"] is True
    assert result["settled"] == 0
    assert result["skipped"] == 1
    assert result["results"][0]["status"] == "SKIPPED"
    assert "datos suficientes" in result["results"][0]["reason"]
