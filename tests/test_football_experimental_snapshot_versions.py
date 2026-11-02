from datetime import datetime, timedelta, timezone

import football_history


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table):
        self.table = table
        self.filters = []

    def upsert(self, payload, **kwargs):
        self.table.upsert_payload = payload
        return self

    def select(self, fields):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def in_(self, key, values):
        self.table.in_filter = (key, values)
        return self

    def limit(self, count):
        return self

    def execute(self):
        if self.table.name == "football_prediction_snapshots" and self.table.upsert_payload:
            return FakeResponse([{"id": "snapshot-1"}])
        return FakeResponse(self.table.pending_rows)


class FakeTable:
    def __init__(self, name):
        self.name = name
        self.upsert_payload = None
        self.pending_rows = []
        self.in_filter = None

    def upsert(self, payload, **kwargs):
        self.upsert_payload = payload
        return FakeQuery(self)

    def select(self, fields):
        return FakeQuery(self)

    def update(self, payload):
        self.updated_payload = payload
        return FakeQuery(self)


class FakeSupabase:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        self.tables.setdefault(name, FakeTable(name))
        return self.tables[name]


def test_form_elo_shadow_snapshot_is_persisted(monkeypatch):
    client = FakeSupabase()
    monkeypatch.setattr(football_history, "get_supabase_client", lambda: client)
    match = {
        "id": 987654,
        "utcDate": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "homeTeam": {"name": "RB Bragantino"},
        "awayTeam": {"name": "Santos FC"},
    }
    prediction = {
        "available": True,
        "model_version": "FOOTBALL-FORM-ELO-SHADOW-0.1.0",
        "probabilities": {"home": 0.455, "draw": 0.211, "away": 0.334},
        "expected_goals": {"home": 2.06, "away": 1.75},
    }

    assert football_history.record_experimental_snapshot(match, "BSA", prediction) is True
    saved = client.tables["football_prediction_snapshots"].upsert_payload
    assert saved["model_version"] == "FOOTBALL-FORM-ELO-SHADOW-0.1.0"
    assert saved["provider_match_id"] == 987654


def test_settlement_query_includes_form_elo_version(monkeypatch):
    client = FakeSupabase()
    table = FakeTable("football_prediction_snapshots")
    table.pending_rows = [{"model_version": "FOOTBALL-FORM-ELO-SHADOW-0.1.0"}]
    client.tables["football_prediction_snapshots"] = table
    monkeypatch.setattr(football_history, "get_supabase_client", lambda: client)
    match = {
        "id": 987654,
        "status": "FINISHED",
        "score": {"fullTime": {"home": 2, "away": 1}},
    }

    assert football_history.settle_experimental_results(match) is True
    assert table.in_filter[0] == "model_version"
    assert "FOOTBALL-FORM-ELO-SHADOW-0.1.0" in table.in_filter[1]
