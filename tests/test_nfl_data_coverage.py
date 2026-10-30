import requests

import nfl_data_coverage as coverage


class FakeResponse:
    def __init__(self, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def head(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.responses.pop(0)


def test_audit_reports_schedule_field_coverage(monkeypatch):
    monkeypatch.setattr(
        coverage,
        "load_schedule",
        lambda season: [
            {"kickoff": "2026-10-01T17:00:00+00:00", "home_score": 10,
             "away_score": 7, "home_qb": "QB A", "wind": None},
            {"kickoff": "2026-10-02T17:00:00+00:00", "home_score": None,
             "away_score": None, "home_qb": None, "wind": 5},
        ],
    )
    session = FakeSession([
        FakeResponse(200, {"Content-Length": "1200"}),
        FakeResponse(404),
        FakeResponse(200),
        FakeResponse(200),
    ])

    result = coverage.audit_nfl_data_coverage(2026, session=session)

    assert result["success"] is True
    assert result["model_version"] == "NFL-1.0.0"
    assert result["model_impact"] == "none"
    assert result["schedule"]["games_found"] == 2
    assert result["schedule"]["valid_kickoff"] == 2
    assert result["schedule"]["games_with_both_scores"] == 1

    fields = {item["field"]: item for item in result["schedule"]["fields"]}
    assert fields["home_qb"]["coverage_pct"] == 50.0
    assert fields["wind"]["coverage_pct"] == 50.0
    assert fields["spread_line"]["coverage_pct"] == 0.0

    assert result["advanced_sources"]["checked"] == 4
    assert result["advanced_sources"]["available"] == 3
    assert len(session.calls) == 4
    assert all(call[1]["timeout"] == coverage.SOURCE_TIMEOUT_SECONDS for call in session.calls)


def test_audit_handles_source_timeout_without_failing(monkeypatch):
    monkeypatch.setattr(coverage, "load_schedule", lambda season: [])
    session = FakeSession(error=requests.Timeout("timed out"))

    result = coverage.audit_nfl_data_coverage(2026, session=session)

    assert result["success"] is True
    assert result["schedule"]["games_found"] == 0
    assert result["advanced_sources"]["available"] == 0
    assert all(source["error"].startswith("Fuente temporalmente no verificable")
               for source in result["advanced_sources"]["sources"])


def test_audit_can_skip_external_source_probes(monkeypatch):
    monkeypatch.setattr(coverage, "load_schedule", lambda season: [])
    session = FakeSession()

    result = coverage.audit_nfl_data_coverage(
        2026,
        include_source_probes=False,
        session=session,
    )

    assert result["advanced_sources"]["checked"] == 0
    assert session.calls == []
