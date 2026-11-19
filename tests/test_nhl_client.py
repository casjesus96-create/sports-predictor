from datetime import date

import pytest

import nhl_client


def test_normalize_game_keeps_missing_scores_as_none():
    result = nhl_client.normalize_game({
        "id": 2026020123,
        "gameDate": "2026-11-18",
        "startTimeUTC": "2026-11-19T00:00:00Z",
        "gameState": "FUT",
        "gameType": 2,
        "homeTeam": {"id": 1, "abbrev": "FLA", "commonName": {"default": "Panthers"}},
        "awayTeam": {"id": 2, "abbrev": "BOS", "commonName": {"default": "Bruins"}},
        "venue": {"default": "Amerant Bank Arena"},
    })
    assert result["game_id"] == "2026020123"
    assert result["home"]["name"] == "Panthers"
    assert result["away"]["abbreviation"] == "BOS"
    assert result["home"]["score"] is None
    assert result["completed"] is False


def test_normalize_game_preserves_live_score_shots_and_period():
    result = nhl_client.normalize_game({
        "id": 2026020123,
        "gameDate": "2026-11-18",
        "gameState": "LIVE",
        "periodDescriptor": {"number": 2, "periodType": "REG"},
        "homeTeam": {"id": 1, "abbrev": "FLA", "score": 2, "sog": 21},
        "awayTeam": {"id": 2, "abbrev": "BOS", "score": 1, "sog": 17},
    })

    assert result["completed"] is False
    assert result["game_state"] == "LIVE"
    assert result["period"] == 2
    assert result["period_type"] == "REG"
    assert result["home"]["score"] == 2
    assert result["away"]["score"] == 1
    assert result["home"]["sog"] == 21
    assert result["away"]["sog"] == 17


def test_normalize_game_rejects_missing_identity_or_invalid_date():
    assert nhl_client.normalize_game({"gameDate": "2026-11-18"}) is None
    assert nhl_client.normalize_game({"id": 2026020123, "gameDate": "18/11/2026"}) is None


def test_get_games_uses_date_scoped_public_scoreboard(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"games": [{
                "id": 2026020123,
                "gameDate": "2026-11-18",
                "gameState": "OFF",
                "homeTeam": {"id": 1, "abbrev": "FLA", "commonName": {"default": "Panthers"}, "score": 3, "sog": 30},
                "awayTeam": {"id": 2, "abbrev": "BOS", "commonName": {"default": "Bruins"}, "score": 2, "sog": 25},
            }]}

    def fake_get(url, headers, timeout):
        captured.update({"url": url, "timeout": timeout})
        return Response()

    monkeypatch.setattr(nhl_client.requests, "get", fake_get)
    games = nhl_client.get_games(date(2026, 11, 18))
    assert captured["url"] == "https://api-web.nhle.com/v1/score/2026-11-18"
    assert games[0]["completed"] is True
    assert games[0]["home"]["score"] == 3
    assert games[0]["away"]["sog"] == 25


def test_get_games_rejects_invalid_date():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        nhl_client.get_games("18-11-2026")


def test_boxscore_normalizes_skaters_and_goalies():
    result = nhl_client.normalize_boxscore({
        "playerByGameStats": {
            "homeTeam": {
                "forwards": [{"playerId": 10, "name": {"default": "Player One"}, "goals": 1, "assists": 2, "shots": 4, "toi": "18:32"}],
                "defense": [{"playerId": 11, "name": {"default": "Player Two"}, "blockedShots": 3}],
                "goalies": [{"playerId": 12, "name": {"default": "Goalie One"}, "saves": 28, "shotsAgainst": 30, "savePctg": 0.933}],
            },
            "awayTeam": {"forwards": [], "defense": [], "goalies": []},
        }
    }, "2026020123")
    home = result["teams"]["home"]
    assert len(home["skaters"]) == 2
    assert home["skaters"][0]["points"] is None
    assert home["skaters"][0]["time_on_ice"] == "18:32"
    assert home["goalies"][0]["saves"] == 28
    assert home["goalies"][0]["save_percentage"] == pytest.approx(0.933)


def test_boxscore_rejects_invalid_game_id_and_malformed_payload():
    with pytest.raises(ValueError, match="game_id"):
        nhl_client.get_boxscore("bad-id")
    with pytest.raises(nhl_client.NHLDataError, match="no contiene"):
        nhl_client.normalize_boxscore({}, "2026020123")



def test_boxscore_without_player_stats_is_available_but_not_ready_yet():
    result = nhl_client.normalize_boxscore({
        "id": 2026020123,
        "gameState": "FUT",
        "limitedScoring": False,
    }, "2026020123")

    assert result["success"] is True
    assert result["stats_available"] is False
    assert result["game_state"] == "FUT"
    assert result["teams"]["home"] == {"skaters": [], "goalies": []}
    assert result["teams"]["away"] == {"skaters": [], "goalies": []}


def test_boxscore_reads_nhl_sog_field_as_player_shots():
    result = nhl_client.normalize_boxscore({
        "gameState": "OFF",
        "playerByGameStats": {
            "homeTeam": {
                "forwards": [{
                    "playerId": 10,
                    "name": {"default": "Player One"},
                    "sog": 5,
                }],
                "defense": [],
                "goalies": [],
            },
            "awayTeam": {"forwards": [], "defense": [], "goalies": []},
        },
    }, "2026020123")

    assert result["stats_available"] is True
    assert result["teams"]["home"]["skaters"][0]["shots"] == 5



def test_get_team_season_schedule_normalizes_and_sorts_games(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "currentSeason": 20252026,
                "games": [
                    {
                        "id": 2025020202,
                        "gameDate": "2025-10-12",
                        "gameState": "OFF",
                        "homeTeam": {"id": 1, "abbrev": "TOR", "score": 3},
                        "awayTeam": {"id": 2, "abbrev": "BOS", "score": 2},
                    },
                    {
                        "id": 2025020101,
                        "gameDate": "2025-10-08",
                        "gameState": "OFF",
                        "homeTeam": {"id": 1, "abbrev": "TOR", "score": 4},
                        "awayTeam": {"id": 3, "abbrev": "MTL", "score": 1},
                    },
                ],
            }

    def fake_get(url, headers, timeout):
        captured.update({"url": url, "timeout": timeout})
        return Response()

    monkeypatch.setattr(nhl_client.requests, "get", fake_get)
    result = nhl_client.get_team_season_schedule("tor", "20252026")

    assert captured["url"] == "https://api-web.nhle.com/v1/club-schedule-season/TOR/20252026"
    assert result["total"] == 2
    assert [game["game_date"] for game in result["games"]] == ["2025-10-08", "2025-10-12"]
    assert result["games"][0]["home"]["score"] == 4


@pytest.mark.parametrize("team,season", [
    ("", "20252026"),
    ("TOR/../../score", "20252026"),
    ("TOR", "20252025"),
    ("TOR", "2025202"),
])
def test_get_team_season_schedule_rejects_invalid_parameters(team, season):
    with pytest.raises(ValueError):
        nhl_client.get_team_season_schedule(team, season)


def test_get_team_season_schedule_rejects_malformed_payload(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"games": {}}

    monkeypatch.setattr(nhl_client.requests, "get", lambda *args, **kwargs: Response())
    with pytest.raises(nhl_client.NHLDataError, match="lista de partidos"):
        nhl_client.get_team_season_schedule("TOR", "20252026")
