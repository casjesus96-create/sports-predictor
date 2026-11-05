from datetime import datetime, timezone

import football_api


def _meeting(match_id, home_id, away_id, competition, kickoff="2024-01-01T15:00:00Z"):
    return {
        "id": match_id,
        "utcDate": kickoff,
        "status": "FINISHED",
        "homeTeam": {"id": home_id, "name": "Arsenal" if home_id == 10 else "Hull City"},
        "awayTeam": {"id": away_id, "name": "Hull City" if away_id == 20 else "Arsenal"},
        "competition": {"code": competition, "name": competition},
        "score": {"fullTime": {"home": 2, "away": 1}},
    }


def test_h2h_fallback_uses_cross_competition_team_histories(monkeypatch):
    calls = []

    def provider_call(function, *args, **kwargs):
        calls.append((function.__name__, args, kwargs))
        if function is football_api.get_match_head_to_head:
            return {"matches": []}
        if function is football_api.get_team_matches and args[0] == 10:
            return {"matches": [
                _meeting(101, 10, 20, "FAC"),
                _meeting(102, 10, 20, "PL", "2024-02-01T15:00:00Z"),
                _meeting(103, 10, 20, "FAC", "2026-11-08T15:00:00Z"),
            ]}
        if function is football_api.get_team_matches and args[0] == 20:
            return {"matches": [
                _meeting(101, 10, 20, "FAC"),
                _meeting(102, 10, 20, "PL", "2024-02-01T15:00:00Z"),
                _meeting(103, 10, 20, "FAC", "2026-11-08T15:00:00Z"),
            ]}
        raise AssertionError(f"Unexpected provider call: {function.__name__} {args}")

    monkeypatch.setattr(football_api, "_provider_call", provider_call)

    result = football_api.football_head_to_head(
        competition="PL",
        home_team_id=10,
        away_team_id=20,
        match_id=999,
        kickoff_at="2026-11-07T11:00:00Z",
        limit=10,
    )

    assert result["sample_size"] == 2
    assert {row["competition_code"] for row in result["meetings"]} == {"FAC", "PL"}
    assert all(row["id"] != 103 for row in result["meetings"])
    team_calls = [call for call in calls if call[0] == "get_team_matches"]
    assert len(team_calls) == 2
    assert all(call[1][1] is None for call in team_calls)
    assert result["history_strategy"] == "cross_competition_team_histories"
    assert result["summary"]["home_team_wins"] == 2


def test_h2h_rate_limit_does_not_trigger_team_history_fallback(monkeypatch):
    from fastapi import HTTPException

    calls = []

    def provider_call(function, *args, **kwargs):
        calls.append(function.__name__)
        raise HTTPException(status_code=429, detail="rate limited")

    monkeypatch.setattr(football_api, "_provider_call", provider_call)

    result = football_api.football_head_to_head(
        competition="PL",
        home_team_id=10,
        away_team_id=20,
        match_id=999,
        kickoff_at="2026-11-07T11:00:00Z",
        limit=10,
    )

    assert result["availability"] == "rate_limited"
    assert result["sample_size"] == 0
    assert calls == ["get_match_head_to_head"]
