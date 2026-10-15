from tennis_client import get_matches, normalize_scoreboard


def test_normalize_scoreboard_extracts_atp_singles_and_scores():
    payload = {
        "events": [{
            "id": "tournament-2026",
            "name": "Example Open",
            "date": "2026-10-15T10:00Z",
            "groupings": [{
                "grouping": {"displayName": "Men's Singles"},
                "competitions": [{
                    "id": "match-1",
                    "date": "2026-10-15T10:00Z",
                    "type": {"text": "Men's Singles"},
                    "round": {"displayName": "Quarterfinal"},
                    "status": {"type": {"state": "pre", "description": "Scheduled", "completed": False}},
                    "competitors": [
                        {
                            "id": "p1",
                            "homeAway": "home",
                            "athlete": {"displayName": "Player One", "flag": {"alt": "USA"}},
                            "linescores": [{"value": 6}, {"value": 4}],
                        },
                        {
                            "id": "p2",
                            "homeAway": "away",
                            "athlete": {"displayName": "Player Two", "flag": {"alt": "ESP"}},
                            "linescores": [],
                        },
                    ],
                }],
            }],
        }],
    }

    matches = normalize_scoreboard(payload, "ATP")

    assert len(matches) == 1
    match = matches[0]
    assert match["match_id"] == "match-1"
    assert match["event_id"] == "tournament-2026"
    assert match["league"] == "ATP"
    assert match["tournament"] == "Example Open"
    assert match["round"] == "Quarterfinal"
    assert match["player1"]["name"] == "Player One"
    assert match["player1"]["sets"] == ["6", "4"]
    assert match["player2"]["country"] == "ESP"
    assert match["completed"] is False


def test_normalize_scoreboard_ignores_doubles_and_deduplicates_matches():
    competition = {
        "id": "same-match",
        "type": {"text": "Men's Singles"},
        "status": {"type": {"state": "post", "completed": True}},
        "competitors": [
            {"id": "1", "homeAway": "home", "athlete": {"displayName": "A"}},
            {"id": "2", "homeAway": "away", "athlete": {"displayName": "B"}},
        ],
    }
    payload = {
        "events": [{
            "id": "event",
            "name": "Tournament",
            "groupings": [{
                "grouping": {"displayName": "Men's Singles"},
                "competitions": [competition],
            }],
            "competitions": [competition, {
                **competition,
                "id": "doubles-match",
                "type": {"text": "Men's Doubles"},
            }],
        }],
    }

    matches = normalize_scoreboard(payload, "ATP")

    assert len(matches) == 1
    assert matches[0]["match_id"] == "same-match"


def test_get_matches_validates_league_and_date_range():
    try:
        get_matches(league="ATP", days=31, start_date="2026-10-15")
    except ValueError as exc:
        assert "between 1 and 30" in str(exc)
    else:
        raise AssertionError("Expected invalid day range to be rejected")

    try:
        get_matches(league="ATP", days=7, start_date="15-10-2026")
    except ValueError as exc:
        assert "YYYY-MM-DD" in str(exc)
    else:
        raise AssertionError("Expected invalid date to be rejected")


def test_get_matches_normalizes_league_and_filters_date(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "events": [{
                    "id": "event",
                    "name": "Open",
                    "groupings": [{
                        "grouping": {"displayName": "Men's Singles"},
                        "competitions": [{
                            "id": "match-in-range",
                            "date": "2026-10-15T12:00:00Z",
                            "type": {"text": "Men's Singles"},
                            "status": {"type": {"state": "pre", "completed": False}},
                            "competitors": [
                                {"homeAway": "home", "athlete": {"displayName": "A"}},
                                {"homeAway": "away", "athlete": {"displayName": "B"}},
                            ],
                        }, {
                            "id": "match-out-of-range",
                            "date": "2026-11-15T12:00:00Z",
                            "type": {"text": "Men's Singles"},
                            "status": {"type": {"state": "pre", "completed": False}},
                            "competitors": [
                                {"homeAway": "home", "athlete": {"displayName": "C"}},
                                {"homeAway": "away", "athlete": {"displayName": "D"}},
                            ],
                        }],
                    }],
                }]
            }

    captured = {}

    def fake_get(url, params, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return Response()

    monkeypatch.setattr("tennis_client.requests.get", fake_get)

    matches = get_matches(league="atp", days=2, start_date="2026-10-15")

    assert captured["url"].endswith("/atp/scoreboard")
    assert captured["params"]["dates"] == "20261015-20261016"
    assert [match["match_id"] for match in matches] == ["match-in-range"]
