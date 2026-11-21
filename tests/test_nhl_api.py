from types import SimpleNamespace

import nhl_api


class _Query:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args):
        return self

    def range(self, *_args):
        return self

    def execute(self):
        if self.error:
            raise self.error
        return SimpleNamespace(data=self.rows)


class _Supabase:
    def __init__(self, rows=None, error=None):
        self.query = _Query(rows=rows, error=error)

    def table(self, _name):
        return self.query


def _game():
    return {
        "game_id": "2026020361",
        "game_date": "2026-11-21",
        "game_type": 2,
        "home": {"abbreviation": "FLA"},
        "away": {"abbreviation": "BUF"},
    }


def test_nhl_games_reports_empty_archive_as_available_and_sample_insufficient(monkeypatch):
    monkeypatch.setattr(nhl_api, "get_games", lambda _date: [_game()])
    monkeypatch.setattr(nhl_api, "get_supabase_client", lambda: _Supabase())
    monkeypatch.setattr(nhl_api, "resolve_team_identity", lambda _season, abbreviation: abbreviation)

    result = nhl_api.nhl_games("2026-11-21")

    assert result["research_archive_status"] == "AVAILABLE"
    assert result["research_archive_rows"] == 0
    assert result["research_archive_error_code"] is None
    assert result["games"][0]["research_prediction"]["status"] == "INSUFFICIENT_HISTORICAL_SAMPLE"
    assert result["games"][0]["research_prediction"]["probabilities"] is None


def test_nhl_games_classifies_archive_permission_error(monkeypatch):
    class PermissionError(Exception):
        code = "42501"

    monkeypatch.setattr(nhl_api, "get_games", lambda _date: [_game()])
    monkeypatch.setattr(
        nhl_api,
        "get_supabase_client",
        lambda: _Supabase(error=PermissionError("permission denied for table nhl_game_archive")),
    )
    monkeypatch.setattr(nhl_api, "resolve_team_identity", lambda _season, abbreviation: abbreviation)

    result = nhl_api.nhl_games("2026-11-21")

    assert result["research_archive_status"] == "ARCHIVE_PERMISSION_DENIED"
    assert result["research_archive_error_code"] == "42501"
    assert result["games"][0]["research_prediction"]["status"] == "ARCHIVE_PERMISSION_DENIED"


def test_nhl_games_classifies_missing_supabase_configuration(monkeypatch):
    monkeypatch.setattr(nhl_api, "get_games", lambda _date: [_game()])

    def _missing_config():
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY")

    monkeypatch.setattr(nhl_api, "get_supabase_client", _missing_config)
    monkeypatch.setattr(nhl_api, "resolve_team_identity", lambda _season, abbreviation: abbreviation)

    result = nhl_api.nhl_games("2026-11-21")

    assert result["research_archive_status"] == "ARCHIVE_CONFIGURATION_ERROR"
    assert result["games"][0]["research_prediction"]["status"] == "ARCHIVE_CONFIGURATION_ERROR"
