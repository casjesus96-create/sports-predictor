from fastapi import HTTPException

import football_api


HOME_ID = 86
AWAY_ID = 81


def finished(match_id, home_id, away_id, home_score, away_score, date="2026-01-01T00:00:00Z"):
    return {
        "id": match_id,
        "status": "FINISHED",
        "utcDate": date,
        "competition": {"name": "Competition", "code": "PD"},
        "homeTeam": {"id": home_id, "name": f"Team {home_id}"},
        "awayTeam": {"id": away_id, "name": f"Team {away_id}"},
        "score": {"fullTime": {"home": home_score, "away": away_score}},
    }


def test_h2h_uses_only_completed_valid_direct_meetings_and_deduplicates(monkeypatch):
    meetings = [
        finished(1, HOME_ID, AWAY_ID, 2, 1, "2026-05-01T00:00:00Z"),
        finished(2, AWAY_ID, HOME_ID, 1, 1, "2025-05-01T00:00:00Z"),
        finished(1, HOME_ID, AWAY_ID, 2, 1, "2026-05-01T00:00:00Z"),
        {
            **finished(3, HOME_ID, AWAY_ID, 5, 0),
            "status": "SCHEDULED",
        },
        {
            **finished(4, HOME_ID, AWAY_ID, 0, 0),
            "score": {"fullTime": {"home": None, "away": None}},
        },
        finished(5, HOME_ID, 999, 4, 0),
        {
            **finished(6, HOME_ID, AWAY_ID, True, 0),
        },
    ]

    def provider_call(function, *args, **kwargs):
        if function is football_api.get_match_head_to_head:
            return {"matches": meetings}
        raise AssertionError("Fallback should not be used when provider H2H has valid matches")

    monkeypatch.setattr(football_api, "_provider_call", provider_call)

    result = football_api.football_head_to_head(
        competition="PD",
        home_team_id=HOME_ID,
        away_team_id=AWAY_ID,
        match_id=123,
        limit=10,
    )

    assert result["sample_size"] == 2
    assert result["returned_matches"] == 2
    assert [item["id"] for item in result["meetings"]] == [1, 2]
    assert result["summary"]["home_team_wins"] == 1
    assert result["summary"]["draws"] == 1
    assert result["summary"]["away_team_wins"] == 0
    # Goals are oriented to the selected fixture, even when the historical home side changes.
    assert result["summary"]["home_team_goals"] == 3
    assert result["summary"]["away_team_goals"] == 2
    assert result["summary"]["both_teams_scored_count"] == 2
    assert result["summary"]["over_2_5_count"] == 1
    assert result["summary"]["under_2_5_count"] == 1


def test_h2h_falls_back_to_competition_history_when_provider_returns_empty(monkeypatch):
    home_history = {
        "matches": [finished(10, HOME_ID, AWAY_ID, 1, 0)],
    }
    away_history = {
        "matches": [finished(10, HOME_ID, AWAY_ID, 1, 0)],
    }

    def provider_call(function, *args, **kwargs):
        if function is football_api.get_match_head_to_head:
            return {"matches": []}
        if function is football_api.get_team_matches and args[0] == HOME_ID:
            return home_history
        if function is football_api.get_team_matches and args[0] == AWAY_ID:
            return away_history
        raise AssertionError(f"Unexpected provider call: {function.__name__}")

    monkeypatch.setattr(football_api, "_provider_call", provider_call)

    result = football_api.football_head_to_head(
        competition="PD",
        home_team_id=HOME_ID,
        away_team_id=AWAY_ID,
        match_id=123,
        limit=10,
    )

    assert result["sample_size"] == 1
    assert "no equivale al historial completo" in result["history_scope"]


def test_h2h_falls_back_when_fixture_id_is_not_provided(monkeypatch):
    def provider_call(function, *args, **kwargs):
        if function is football_api.get_team_matches and args[0] == HOME_ID:
            return {"matches": [finished(11, HOME_ID, AWAY_ID, 0, 0)]}
        if function is football_api.get_team_matches and args[0] == AWAY_ID:
            return {"matches": [finished(11, HOME_ID, AWAY_ID, 0, 0)]}
        raise AssertionError("Dedicated H2H endpoint should not be called without match_id")

    monkeypatch.setattr(football_api, "_provider_call", provider_call)

    result = football_api.football_head_to_head(
        competition="PD",
        home_team_id=HOME_ID,
        away_team_id=AWAY_ID,
        match_id=None,
        limit=10,
    )

    assert result["sample_size"] == 1
    assert "competición seleccionada" in result["history_scope"]


def test_h2h_rejects_same_team_ids():
    try:
        football_api.football_head_to_head(
            competition="PD",
            home_team_id=HOME_ID,
            away_team_id=HOME_ID,
            match_id=123,
            limit=10,
        )
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected same-team IDs to be rejected")
