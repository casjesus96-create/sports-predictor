from datetime import datetime, timedelta, timezone

import football_api


def test_experimental_endpoint_returns_visible_side_by_side_candidate(monkeypatch):
    kickoff = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    monkeypatch.setattr(football_api, "get_matches", lambda competition: {"matches": []})
    monkeypatch.setattr(
        football_api,
        "predict_1x2",
        lambda home, away, completed: {
            "available": True,
            "model_version": "FOOTBALL-POISSON-0.5.0",
            "probabilities": {"home": 0.40, "draw": 0.30, "away": 0.30},
        },
    )
    monkeypatch.setattr(
        football_api,
        "football_head_to_head",
        lambda **kwargs: {
            "meetings": [
                {
                    "id": 1, "date": "2026-01-01T12:00:00Z",
                    "home_team_id": 10, "away_team_id": 20,
                    "home_score": 1, "away_score": 3,
                },
                {
                    "id": 2, "date": "2025-01-01T12:00:00Z",
                    "home_team_id": 20, "away_team_id": 10,
                    "home_score": 2, "away_score": 0,
                },
                {
                    "id": 3, "date": "2024-01-01T12:00:00Z",
                    "home_team_id": 10, "away_team_id": 20,
                    "home_score": 1, "away_score": 1,
                },
            ]
        },
    )

    result = football_api.football_experimental_h2h(
        competition="BL1",
        home_team_id=10,
        away_team_id=20,
        match_id=999,
        home_team="SC Freiburg",
        away_team="FC Bayern München",
        kickoff_at=kickoff,
    )

    assert result["success"] is True
    assert result["mode"] == "SHADOW_ONLY"
    assert result["official_model_version"] == "FOOTBALL-POISSON-0.5.0"
    assert result["candidate"]["h2h"]["valid_meetings"] == 3
    assert set(result["candidate"]["base_probabilities"]) == {"home", "draw", "away"}
    assert set(result["candidate"]["candidate_probabilities"]) == {"home", "draw", "away"}
    assert abs(sum(result["candidate"]["candidate_probabilities"].values()) - 1.0) < 1e-9


def test_experimental_endpoint_rejects_kickoff_without_timezone():
    kickoff = (datetime.now(timezone.utc) + timedelta(days=2)).replace(tzinfo=None).isoformat()
    try:
        football_api.football_experimental_h2h(
            competition="BL1",
            home_team_id=10,
            away_team_id=20,
            match_id=999,
            home_team="SC Freiburg",
            away_team="FC Bayern München",
            kickoff_at=kickoff,
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("Expected HTTP 400 for a timezone-naive kickoff")


def test_experimental_endpoint_rejects_same_team_ids():
    try:
        football_api.football_experimental_h2h(
            competition="BL1",
            home_team_id=10,
            away_team_id=10,
            match_id=999,
            home_team="SC Freiburg",
            away_team="FC Bayern München",
            kickoff_at=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("Expected HTTP 400 for identical team IDs")
