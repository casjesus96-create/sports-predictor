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
    assert "no incluye" in response["history_scope"]
