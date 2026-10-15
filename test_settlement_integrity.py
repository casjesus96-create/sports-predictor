"""Regression tests for safe MLB prediction settlement."""

from copy import deepcopy

import repository


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.operation = "select"
        self.payload = None
        self.filters = {}

    def select(self, _fields):
        self.operation = "select"
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = deepcopy(payload)
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def execute(self):
        if self.operation == "update":
            self.client.updated.append(
                {"filters": dict(self.filters), "payload": self.payload}
            )
            row = deepcopy(self.client.row)
            row.update(self.payload)
            return FakeResponse([row])

        row = self.client.row
        for key, value in self.filters.items():
            if row.get(key) != value:
                return FakeResponse([])
        return FakeResponse([deepcopy(row)])


class FakeSupabase:
    def __init__(self, row):
        self.row = deepcopy(row)
        self.updated = []

    def table(self, table_name):
        assert table_name == "prediction_snapshots"
        return FakeQuery(self, table_name)


def pending_row(features=None, home_probability=0.65, away_probability=0.35):
    return {
        "id": "snapshot-1",
        "event_id": "game-123",
        "model_version": "2.0.0-matchup",
        "result_status": "PENDING",
        "home_probability": home_probability,
        "away_probability": away_probability,
        "features": features if features is not None else {
            "game": {"home": "Home Team", "away": "Away Team"},
            "predicted_winner": "Home Team",
        },
    }


def test_settlement_uses_saved_prediction_and_preserves_probabilities(monkeypatch):
    row = pending_row()
    client = FakeSupabase(row)
    monkeypatch.setattr(repository, "get_supabase_client", lambda: client)

    result = repository.settle_prediction(
        event_id="game-123",
        actual_winner="Home Team",
        actual_home_score=5,
        actual_away_score=2,
    )

    assert result["updated"] is True
    assert result["prediction_result"] == "CORRECT"
    payload = client.updated[0]["payload"]
    assert payload["result_status"] == "SETTLED"
    assert payload["prediction_result"] == "CORRECT"
    assert payload["actual_winner"] == "Home Team"
    assert payload["actual_home_score"] == 5
    assert payload["actual_away_score"] == 2
    assert payload["settled_at"]
    assert set(payload).isdisjoint({
        "home_probability", "away_probability", "confidence", "model_version"
    })
    assert client.row["home_probability"] == row["home_probability"]
    assert client.row["away_probability"] == row["away_probability"]
    assert client.row["model_version"] == row["model_version"]


def test_missing_predicted_winner_never_uses_actual_winner(monkeypatch):
    row = pending_row(
        features={"game": {"home": "Home Team", "away": "Away Team"}},
        home_probability=0.65,
        away_probability=0.35,
    )
    client = FakeSupabase(row)
    monkeypatch.setattr(repository, "get_supabase_client", lambda: client)

    result = repository.settle_prediction(
        event_id="game-123",
        actual_winner="Away Team",
        actual_home_score=1,
        actual_away_score=4,
    )

    assert result["updated"] is True
    assert result["predicted_winner"] == "Home Team"
    assert result["prediction_result"] == "INCORRECT"


def test_incomplete_prediction_stays_pending_for_review(monkeypatch):
    row = pending_row(
        features={"game": {"home": "Home Team", "away": "Away Team"}},
        home_probability=None,
        away_probability=None,
    )
    client = FakeSupabase(row)
    monkeypatch.setattr(repository, "get_supabase_client", lambda: client)

    result = repository.settle_prediction(
        event_id="game-123",
        actual_winner="Home Team",
        actual_home_score=3,
        actual_away_score=2,
    )

    assert result["updated"] is False
    assert "PENDING" in result["reason"]
    assert client.updated == []


def test_unknown_actual_winner_stays_pending_for_review(monkeypatch):
    client = FakeSupabase(pending_row())
    monkeypatch.setattr(repository, "get_supabase_client", lambda: client)

    result = repository.settle_prediction(
        event_id="game-123",
        actual_winner="Unknown Team",
        actual_home_score=3,
        actual_away_score=2,
    )

    assert result["updated"] is False
    assert "PENDING" in result["reason"]
    assert client.updated == []


def test_already_settled_prediction_is_not_updated_twice(monkeypatch):
    row = pending_row()
    row["result_status"] = "SETTLED"
    row["prediction_result"] = "CORRECT"
    client = FakeSupabase(row)
    monkeypatch.setattr(repository, "get_supabase_client", lambda: client)

    result = repository.settle_prediction(
        event_id="game-123",
        actual_winner="Home Team",
        actual_home_score=5,
        actual_away_score=2,
    )

    assert result["updated"] is False
    assert client.updated == []
