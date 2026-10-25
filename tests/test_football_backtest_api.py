from football_api import football_chronological_backtest
from football_model import MODEL_VERSION


def fixture(match_id, home, away, home_goals, away_goals, date, status="FINISHED"):
    return {
        "id": match_id,
        "status": status,
        "utcDate": date,
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "score": {"fullTime": {"home": home_goals, "away": away_goals}},
    }


def test_backtest_endpoint_uses_provider_data_and_returns_read_only_metrics(monkeypatch):
    scores = [(2, 0), (1, 1), (0, 1), (3, 1), (1, 0), (2, 2), (0, 2), (2, 1)]
    matches = []
    for i, (hg, ag) in enumerate(scores, start=1):
        home, away = ("Alpha", "Beta") if i % 2 else ("Beta", "Alpha")
        matches.append(fixture(
            i, home, away, hg, ag, f"2026-01-{i:02d}T15:00:00Z"
        ))

    monkeypatch.setattr(
        "football_api._provider_call",
        lambda function, competition: {"matches": matches},
    )
    response = football_chronological_backtest("PL")

    assert response["success"] is True
    assert response["competition"] == "PL"
    assert response["backtest"]["official_model_version"] == MODEL_VERSION
    assert response["backtest"]["read_only"] is True
    assert response["backtest"]["scored_matches"] > 0
    assert "no se escriben snapshots" in response["history_scope"]
    assert response["backtest"]["external_h2h_lookup"]["requested"] is False
    assert response["backtest"]["h2h_diagnostics"]["matches_using_external_provider_h2h"] == 0


def test_backtest_external_h2h_is_opt_in_and_bounded(monkeypatch):
    import football_api

    matches = [fixture(i, "Alpha" if i % 2 else "Beta", "Beta" if i % 2 else "Alpha", i % 3, (i + 1) % 3, f"2026-01-{i:02d}T15:00:00Z") for i in range(1, 9)]
    for match in matches:
        match["homeTeam"]["id"] = 1 if match["homeTeam"]["name"] == "Alpha" else 2
        match["awayTeam"]["id"] = 1 if match["awayTeam"]["name"] == "Alpha" else 2
    calls = []

    def fake_provider_call(function, *args, **kwargs):
        if function.__name__ == "get_matches":
            return {"matches": matches}
        if function.__name__ == "get_match_head_to_head":
            calls.append(args[0])
            return {"matches": matches}
        raise AssertionError(f"Unexpected provider function: {function.__name__}")

    monkeypatch.setattr(football_api, "_provider_call", fake_provider_call)
    response = football_chronological_backtest("PL", include_external_h2h=True)
    lookup = response["backtest"]["external_h2h_lookup"]
    assert lookup["requested"] is True
    assert lookup["attempted"] <= 20
    assert lookup["attempted"] == len(calls)
    assert response["backtest"]["h2h_diagnostics"]["matches_using_external_provider_h2h"] > 0
    assert all(row["h2h_source"] in {"provider_external_h2h", "competition_history"} for row in response["backtest"]["per_match"])
