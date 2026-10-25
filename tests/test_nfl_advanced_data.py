import gzip
import io

import requests

import nfl_advanced_data as advanced


def _gz(value):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb") as zipped:
        zipped.write(value.encode("utf-8"))
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, content=b"", status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


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


def test_scan_csv_gzip_finds_columns_rows_and_keys():
    result = advanced._scan_csv_gzip(_gz(
        "season,week,team,game_id,epa\n"
        "2026,1,BUF,g1,0.2\n"
        "2026,2,BUF,g2,0.4\n"
        "2026,1,MIA,g1,-0.1\n"
    ))
    assert result["columns"] == ["season", "week", "team", "game_id", "epa"]
    assert result["rows_scanned"] == 3
    assert result["seasons"] == ["2026"]
    assert result["weeks"] == ["1", "2"]
    assert result["distinct_teams"] == 2
    assert result["distinct_games"] == 2


def test_source_inspection_continues_after_http_error():
    valid = _gz("season,week,team\n2026,1,BUF\n")
    session = FakeSession([
        FakeResponse(valid), FakeResponse(b"", 404),
        FakeResponse(valid), FakeResponse(valid),
    ])
    result = advanced.inspect_nfl_advanced_sources(2026, session=session)
    assert result["success"] is True
    assert result["model_impact"] == "none"
    assert result["sources_checked"] == 4
    assert result["sources_inspected"] == 3
    assert len(session.calls) == 4


def test_source_inspection_handles_timeouts():
    session = FakeSession([requests.Timeout("timeout")] * 4)
    result = advanced.inspect_nfl_advanced_sources(2026, session=session)
    assert result["sources_inspected"] == 0
    assert all(item["error"] for item in result["sources"])
