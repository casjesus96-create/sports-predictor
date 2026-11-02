from football_form_elo_experiment import EXPERIMENT_VERSION, predict_form_elo


def make_match(mid, date, home_id, away_id, hg, ag):
    return {
        "id": mid, "status": "FINISHED", "utcDate": date,
        "homeTeam": {"id": home_id, "name": f"Team {home_id}"},
        "awayTeam": {"id": away_id, "name": f"Team {away_id}"},
        "score": {"fullTime": {"home": hg, "away": ag}},
        "competition": {"code": "PL"},
    }


def histories():
    home, away = [], []
    # Both target teams have six completed matches against distinct opponents.
    for i in range(6):
        date = f"2026-09-{10+i:02d}T15:00:00Z"
        home.append(make_match(i + 1, date, 10, 20 + i, 0 if i < 4 else 2, 2 if i < 4 else 0))
        away.append(make_match(i + 20, date, 30 + i, 11, 0, 2))
    return home, away


def test_form_elo_returns_valid_shadow_probabilities():
    home, away = histories()
    result = predict_form_elo(
        10, 11, "Home", "Away", "2026-10-01T15:00:00Z",
        home, away, {"home": 1.45, "away": 1.15},
    )
    assert result["available"] is True
    assert result["model_version"] == EXPERIMENT_VERSION
    assert result["status"] == "SHADOW_ONLY"
    assert abs(sum(result["probabilities"].values()) - 1) < 1e-5
    assert result["sample"]["home_matches"] == 6
    assert result["sample"]["away_matches"] == 6


def test_form_elo_excludes_future_matches():
    home, away = histories()
    home.append(make_match(99, "2026-10-02T15:00:00Z", 10, 11, 9, 0))
    result = predict_form_elo(
        10, 11, "Home", "Away", "2026-10-01T15:00:00Z",
        home, away, {"home": 1.45, "away": 1.15},
    )
    assert result["available"] is True
    assert result["sample"]["home_matches"] == 6


def test_form_elo_requires_verified_target_baseline():
    home, away = histories()
    result = predict_form_elo(
        10, 11, "Home", "Away", "2026-10-01T15:00:00Z",
        home, away, None,
    )
    assert result["available"] is False
    assert "media goleadora" in result["reason"]
