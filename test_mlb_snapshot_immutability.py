from types import SimpleNamespace

import repository


class FakeSupabase:
    def __init__(self, existing_rows=None):
        self.existing_rows = existing_rows or []
        self.operation = None
        self.payload = None
        self.update_called = False
        self.insert_called = False

    def table(self, _name):
        return self

    def select(self, _columns):
        self.operation = "select"
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def update(self, payload):
        self.update_called = True
        self.payload = payload
        self.operation = "update"
        return self

    def insert(self, payload):
        self.insert_called = True
        self.payload = payload
        self.operation = "insert"
        return self

    def execute(self):
        if self.operation == "select":
            return SimpleNamespace(data=self.existing_rows)
        if self.operation in ("insert", "update"):
            return SimpleNamespace(data=[self.payload])
        raise AssertionError(f"Unexpected operation: {self.operation}")


def make_analysis(home=0.63, away=0.37):
    return {
        "success": True,
        "model_version": "2.0.0-matchup",
        "generated_at": "2026-10-01T12:00:00+00:00",
        "game": {"game_id": "123456", "home": "Home Team", "away": "Away Team"},
        "prediction": {
            "winner": "Home Team" if home >= away else "Away Team",
            "home_probability": home,
            "away_probability": away,
            "confidence": 0.63,
            "data_quality": 85,
        },
        "factors": {"example": "feature"},
    }


def test_existing_pending_snapshot_is_preserved(monkeypatch):
    original = {
        "id": "snapshot-1", "event_id": "123456",
        "model_version": "2.0.0-matchup",
        "created_at": "2026-09-30T12:00:00+00:00",
        "home_probability": 0.54, "away_probability": 0.46,
        "result_status": "PENDING", "features": {"predicted_winner": "Away Team"},
    }
    client = FakeSupabase([original])
    monkeypatch.setattr(repository, "get_supabase_client", lambda: client)

    result = repository.save_analysis(make_analysis(0.91, 0.09))

    assert result["existing_prediction_preserved"] is True
    assert result["updated_existing"] is False
    assert result["data"] == [original]
    assert result["data"][0]["home_probability"] == 0.54
    assert result["data"][0]["created_at"] == "2026-09-30T12:00:00+00:00"
    assert client.update_called is False
    assert client.insert_called is False


def test_new_snapshot_is_inserted_when_none_exists(monkeypatch):
    client = FakeSupabase()
    monkeypatch.setattr(repository, "get_supabase_client", lambda: client)

    result = repository.save_analysis(make_analysis())

    assert result["success"] is True
    assert result["existing_prediction_preserved"] is False
    assert client.insert_called is True
    assert client.update_called is False
    assert result["data"][0]["home_probability"] == 0.63
    assert result["data"][0]["result_status"] == "PENDING"


def test_failed_analysis_does_not_access_database(monkeypatch):
    def fail_if_called():
        raise AssertionError("Database should not be accessed")

    monkeypatch.setattr(repository, "get_supabase_client", fail_if_called)
    result = repository.save_analysis({"success": False})
    assert result["success"] is False
    assert result["saved"] is False
