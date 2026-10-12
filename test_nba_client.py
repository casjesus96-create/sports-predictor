from datetime import date

import nba_client


def test_month_iterator_crosses_year_boundary():
    months = list(nba_client._iter_month_starts(date(2025, 12, 20), date(2026, 2, 3)))
    assert months == [date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]


def test_get_events_uses_month_keys_and_filters_date_range(monkeypatch):
    requested = []

    def fake_month_events(month_start):
        requested.append(month_start.strftime("%Y%m"))
        return [
            {"game_id": f"{month_start:%Y%m}-start", "kickoff": f"{month_start:%Y-%m}-01T20:00:00+00:00"},
            {"game_id": f"{month_start:%Y%m}-middle", "kickoff": f"{month_start:%Y-%m}-15T20:00:00+00:00"},
        ]

    monkeypatch.setattr(nba_client, "_get_month_events", fake_month_events)
    result = nba_client._get_events(date(2026, 10, 9), date(2026, 11, 12))

    assert requested == ["202610", "202611"]
    assert all("-" not in key for key in requested)
    assert [item["game_id"] for item in result] == ["202610-middle", "202611-start"]


def test_get_team_histories_groups_games_for_both_teams(monkeypatch):
    games = [
        {
            "game_id": "one",
            "kickoff": "2026-10-01T20:00:00+00:00",
            "completed": True,
            "home_team_id": "1",
            "away_team_id": "2",
            "home_score": 110.0,
            "away_score": 100.0,
        },
        {
            "game_id": "two",
            "kickoff": "2026-10-02T20:00:00+00:00",
            "completed": True,
            "home_team_id": "3",
            "away_team_id": "1",
            "home_score": 99.0,
            "away_score": 101.0,
        },
    ]
    calls = []
    monkeypatch.setattr(nba_client, "_get_events", lambda start, end: calls.append((start, end)) or games)

    result = nba_client.get_team_histories(["1", "2"], "2026-10-04T00:00:00+00:00", days=30)

    assert len(calls) == 1
    assert [game["game_id"] for game in result["1"]] == ["two", "one"]
    assert [game["game_id"] for game in result["2"]] == ["one"]



def test_boxscore_stats_normalize_basketball_metrics():
    stats = nba_client._normalize_boxscore_stats([
        {"name": "rebounds", "displayValue": "45"},
        {"name": "assists", "displayValue": "27"},
        {"name": "blocks", "displayValue": "6"},
        {"name": "steals", "displayValue": "8"},
        {"name": "turnovers", "displayValue": "13"},
        {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "42-90"},
        {"name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "displayValue": "14-38"},
        {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "18-22"},
    ])

    assert stats["rebounds"] == 45
    assert stats["assists"] == 27
    assert stats["blocks"] == 6
    assert stats["steals"] == 8
    assert stats["turnovers"] == 13
    assert stats["field_goal_pct"] == 46.67
    assert stats["three_point_pct"] == 36.84
    assert stats["free_throw_pct"] == 81.82


def test_boxscore_history_uses_only_selected_recent_games(monkeypatch):
    histories = {
        "1": [
            {"game_id": "10", "kickoff": "2026-10-10T20:00:00+00:00", "home_team_id": "1", "away_team_id": "2"},
        ],
        "2": [
            {"game_id": "10", "kickoff": "2026-10-10T20:00:00+00:00", "home_team_id": "1", "away_team_id": "2"},
        ],
    }

    monkeypatch.setattr(
        nba_client,
        "_get_boxscore_for_game",
        lambda game_id: (game_id, {
            "1": {"rebounds": 44, "assists": 25},
            "2": {"rebounds": 39, "assists": 22},
        }),
    )

    result = nba_client.get_team_boxscore_histories(histories, max_games=5)

    assert result["1"][0]["stats"]["rebounds"] == 44
    assert result["1"][0]["opponent_stats"]["rebounds"] == 39
    assert result["2"][0]["stats"]["assists"] == 22
    assert result["2"][0]["opponent_stats"]["assists"] == 25
