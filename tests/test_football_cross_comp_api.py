from datetime import datetime, timedelta, timezone

import football_api


def make_match(mid, home_id, away_id, hg, ag, day, code):
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
    return {
        "id": mid, "status": "FINISHED", "utcDate": dt.isoformat(),
        "competition": {"code": code},
        "homeTeam": {"id": home_id, "name": f"Team {home_id}"},
        "awayTeam": {"id": away_id, "name": f"Team {away_id}"},
        "score": {"fullTime": {"home": hg, "away": ag}},
    }


def test_cross_comp_api_uses_team_histories_and_competition_baselines(monkeypatch):
    home_history = [make_match(i, 10, 100 + i, 2, 1, i, "PL") for i in range(1, 8)]
    away_history = [make_match(i + 20, 200 + i, 20, 1, 2, i, "PD") for i in range(1, 8)]
    cl_matches = [make_match(i + 40, 300 + i, 400 + i, 1, 1, i, "CL") for i in range(1, 12)]
    pl_matches = [make_match(i + 60, 500 + i, 600 + i, 2, 1, i, "PL") for i in range(1, 12)]
    pd_matches = [make_match(i + 80, 700 + i, 800 + i, 1, 1, i, "PD") for i in range(1, 12)]

    calls = []
    def provider_call(function, *args, **kwargs):
        calls.append((function.__name__, args))
        if function is football_api.get_team_matches:
            return {"matches": home_history if args[0] == 10 else away_history}
        if function is football_api.get_matches:
            return {"matches": pl_matches if args[0] == "PL" else pd_matches}
        raise AssertionError(f"Unexpected provider function: {function}")

    monkeypatch.setattr(football_api, "_provider_call", provider_call)
    original_predict = football_api.predict_cross_competition
    captured = {}
    def spy_predict(*args, **kwargs):
        captured["home_history"] = args[5]
        captured["away_history"] = args[6]
        captured["baselines"] = args[7]
        return original_predict(*args, **kwargs)
    monkeypatch.setattr(football_api, "predict_cross_competition", spy_predict)
    result = football_api._cross_competition_prediction(
        "CL", 10, 20, "Home FC", "Away FC", "2026-02-01T15:00:00+00:00", cl_matches,
    )
    assert calls == [("get_team_matches", (10, None, "FINISHED", 60)), ("get_team_matches", (20, None, "FINISHED", 60)), ("get_matches", ("PL",)), ("get_matches", ("PD",))], calls
    assert len(captured["away_history"]) == 7
    assert captured["baselines"].keys() == {"CL", "PL", "PD"}, captured["baselines"]
    assert result["available"] is True, result
    assert result["status"] == "SHADOW_ONLY"
    assert result["sample"]["home_matches"] == 7
    assert result["sample"]["away_matches"] == 7
    assert set(result["sample"]["competitions_used"]) == {"PL", "PD"}


def test_cross_comp_api_fails_closed_on_provider_rate_limit(monkeypatch):
    def provider_call(*args, **kwargs):
        raise football_api.HTTPException(status_code=429, detail="rate limited")

    monkeypatch.setattr(football_api, "_provider_call", provider_call)
    result = football_api._cross_competition_prediction(
        "CL", 10, 20, "Home FC", "Away FC", "2026-02-01T15:00:00+00:00", [],
    )
    assert result["available"] is False
    assert result["provider_error_status"] == 429
