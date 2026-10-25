import gzip
import io

import requests

import nfl_advanced_data as advanced


def _gzip_csv(value):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb") as stream:
        stream.write(value.encode("utf-8"))
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, content=b"", status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_inspect_csv_gzip_reports_schema_and_temporal_keys():
    content = _gzip_csv(
        "season,week,team,game_id,epa\n"
        "2026,1,BUF,2026_01_BUF_MIA,0.2\n"
        "2026,2,BUF,2026_02_BUF_NYJ,0.4\n"
        "2026,1,MIA,2026_01_BUF_MIA,-0.1\n"
    )
    result = advanced._inspect_csv_gzip(content)
    assert result["columns"] == ["season", "week", "team", "game_id", "epa"]
    assert result["rows_scanned"] == 3
    assert result["seasons"] == ["2026"]
    assert result["weeks"] == ["1", "2"]
    assert result["distinct_games"] == 2
    assert result["distinct_teams"] == 2
    assert result["distinct_team_week_keys"] == 3


def test_inspector_continues_when_one_source_is_unavailable():
    valid = _gzip_csv("season,week,team\n2026,1,BUF\n")
    session = FakeSession([
        FakeResponse(valid),
        FakeResponse(b"", 404),
        FakeResponse(valid),
        FakeResponse(valid),
    ])
    result = advanced.inspect_nfl_advanced_sources(2026, session=session)
    assert result["success"] is True
    assert result["model_impact"] == "none"
    assert result["sources_checked"] == 4
    assert result["sources_inspected"] == 3
    assert result["sources"][1]["available"] is False
    assert len(session.calls) == 4
    assert all(call[1]["timeout"] == advanced.SOURCE_TIMEOUT_SECONDS for call in session.calls)


def test_inspector_handles_network_timeout():
    session = FakeSession([
        requests.Timeout("timeout"),
        requests.Timeout("timeout"),
        requests.Timeout("timeout"),
        requests.Timeout("timeout"),
    ])
    result = advanced.inspect_nfl_advanced_sources(2026, session=session)
    assert result["sources_inspected"] == 0
    assert all(item["error"] for item in result["sources"])
