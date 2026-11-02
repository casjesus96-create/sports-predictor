from datetime import datetime, timedelta, timezone

from football_cross_comp_model import EXPERIMENT_VERSION, predict_cross_competition


def fixture(match_id, home_id, away_id, home_goals, away_goals, day, code="PL"):
    date = (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)).isoformat()
    return {
        "id": match_id, "status": "FINISHED", "utcDate": date,
        "competition": {"code": code},
        "homeTeam": {"id": home_id, "name": f"Team {home_id}"},
        "awayTeam": {"id": away_id, "name": f"Team {away_id}"},
        "score": {"fullTime": {"home": home_goals, "away": away_goals}},
    }


def histories():
    home = [
        fixture(i, 10, 100 + i, 2 if i % 2 else 1, 1, i, "PL")
        for i in range(1, 8)
    ]
    away = [
        fixture(i + 20, 200 + i, 20, 1, 2 if i % 2 else 1, i, "PD")
        for i in range(1, 8)
    ]
    return home, away


def test_cross_comp_candidate_returns_shadow_probabilities_and_expected_goals():
    home, away = histories()
    result = predict_cross_competition(
        10, 20, "Home FC", "Away FC", "2026-02-01T15:00:00Z",
        home, away,
        {"CL": {"home": 1.5, "away": 1.2}, "PL": {"home": 1.6, "away": 1.1},
         "PD": {"home": 1.4, "away": 1.0}},
        "CL",
    )
    assert result["available"] is True
    assert result["status"] == "SHADOW_ONLY"
    assert result["model_version"] == EXPERIMENT_VERSION
    assert abs(sum(result["probabilities"].values()) - 1) < 1e-6
    assert result["expected_goals"]["total"] > 0
    assert result["sample"]["future_matches_excluded"] is True
    assert set(result["sample"]["competitions_used"]) == {"PL", "PD"}


def test_cross_comp_candidate_excludes_future_matches():
    home, away = histories()
    home.append(fixture(99, 10, 999, 8, 0, 80, "PL"))
    away.append(fixture(100, 998, 20, 0, 8, 80, "PD"))
    result = predict_cross_competition(
        10, 20, "Home FC", "Away FC", "2026-02-01T15:00:00Z",
        home, away,
        {"CL": {"home": 1.5, "away": 1.2}, "PL": {"home": 1.6, "away": 1.1},
         "PD": {"home": 1.4, "away": 1.0}},
        "CL",
    )
    assert result["available"] is True
    assert result["sample"]["home_matches"] == 7
    assert result["sample"]["away_matches"] == 7


def test_cross_comp_candidate_requires_five_normalizable_matches_per_team():
    home, away = histories()
    result = predict_cross_competition(
        10, 20, "Home FC", "Away FC", "2026-02-01T15:00:00Z",
        home[:3], away,
        {"CL": {"home": 1.5, "away": 1.2}, "PL": {"home": 1.6, "away": 1.1},
         "PD": {"home": 1.4, "away": 1.0}},
        "CL",
    )
    assert result["available"] is False
    assert result["sample"]["home_matches"] == 3


def test_cross_comp_candidate_fails_closed_without_target_competition_baseline():
    home, away = histories()
    result = predict_cross_competition(
        10, 20, "Home FC", "Away FC", "2026-02-01T15:00:00Z",
        home, away, {"PL": {"home": 1.6, "away": 1.1}, "PD": {"home": 1.4, "away": 1.0}},
        "CL",
    )
    assert result["available"] is False
    assert "media goleadora" in result["reason"]
