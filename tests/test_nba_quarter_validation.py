from nba_quarter_validation import evaluate_quarter_projections


def snapshot(event_id="g1", cutoff="2026-01-01T00:00:00+00:00"):
    return {
        "event_id": event_id,
        "data_cutoff": cutoff,
        "created_at": "2026-01-01T01:00:00+00:00",
        "actual_home_score": 100,
        "actual_away_score": 90,
        "features": {
            "game": {
                "game_id": event_id, "kickoff": "2026-01-02T00:00:00+00:00",
                "home_team_id": "H", "away_team_id": "A", "home": "Home", "away": "Away",
            },
            "projections": {
                "total_points": 190,
                "quarter_points": {"available": True, "periods": [
                    {"home_points": 25, "away_points": 20},
                    {"home_points": 25, "away_points": 22},
                    {"home_points": 25, "away_points": 23},
                    {"home_points": 25, "away_points": 25},
                ]},
            },
        },
    }


def test_validation_calculates_quarter_mae_and_does_not_mutate_snapshot():
    row = snapshot()
    original = repr(row)
    actual = {"g1": {"H": [24, 26, 25, 25], "A": [20, 22, 23, 25]}}
    result = evaluate_quarter_projections([row], actual)
    assert result["evaluated_games"] == 1
    assert result["home_points_mae"] == 0.5
    assert result["away_points_mae"] == 0
    assert result["team_points_mae"] == 0.25
    assert result["quarter_total_mae"] == 0.5
    assert result["game_total_score_mae"] == 0
    assert [x["label"] for x in result["by_quarter"]] == ["Q1", "Q2", "Q3", "Q4"]
    assert repr(row) == original


def test_validation_skips_missing_quarter_scores_and_postgame_cutoff():
    row = snapshot()
    invalid = snapshot("g2", cutoff="2026-01-03T00:00:00+00:00")
    result = evaluate_quarter_projections([row, invalid], {})
    assert result["evaluated_games"] == 0
    assert result["skipped"]["missing_actual_quarters"] == 1
    assert result["skipped"]["invalid_or_postgame_cutoff"] == 1


def test_validation_does_not_treat_missing_projection_as_zero():
    row = snapshot()
    row["features"]["projections"]["quarter_points"]["periods"][0]["home_points"] = None
    actual = {"g1": {"H": [24, 26, 25, 25], "A": [20, 22, 23, 25]}}
    result = evaluate_quarter_projections([row], actual)
    assert result["evaluated_games"] == 0
    assert result["skipped"]["missing_projection"] == 1



def test_validation_allows_cutoff_equal_to_kickoff_when_snapshot_was_captured_before_game():
    row = snapshot(cutoff="2026-01-02T00:00:00+00:00")
    actual = {"g1": {"H": [24, 26, 25, 25], "A": [20, 22, 23, 25]}}
    result = evaluate_quarter_projections([row], actual)
    assert result["evaluated_games"] == 1
    assert result["skipped"]["invalid_or_postgame_cutoff"] == 0


def test_validation_still_rejects_snapshot_created_at_or_after_kickoff():
    row = snapshot(cutoff="2026-01-02T00:00:00+00:00")
    row["created_at"] = "2026-01-02T00:00:00+00:00"
    actual = {"g1": {"H": [24, 26, 25, 25], "A": [20, 22, 23, 25]}}
    result = evaluate_quarter_projections([row], actual)
    assert result["evaluated_games"] == 0
    assert result["skipped"]["invalid_or_postgame_cutoff"] == 1
    assert result["skipped_details"][0]["reason"] == "snapshot_created_at_or_after_kickoff"



def test_selector_keeps_only_latest_valid_pregame_snapshot_per_game():
    from nba_quarter_validation import select_latest_pregame_snapshots

    older = snapshot("g1")
    older["created_at"] = "2026-01-01T01:00:00+00:00"
    newer = snapshot("g1")
    newer["created_at"] = "2026-01-01T02:00:00+00:00"
    postgame = snapshot("g1")
    postgame["created_at"] = "2026-01-02T00:00:00+00:00"
    selected, duplicates = select_latest_pregame_snapshots([older, newer, postgame])

    assert len(selected) == 1
    assert selected[0]["created_at"] == newer["created_at"]
    assert duplicates == 1


def test_selector_keeps_separate_games_and_ignores_invalid_snapshots():
    from nba_quarter_validation import select_latest_pregame_snapshots

    first = snapshot("g1")
    second = snapshot("g2")
    invalid = snapshot("g3")
    invalid["created_at"] = "2026-01-02T00:00:00+00:00"
    selected, duplicates = select_latest_pregame_snapshots([first, second, invalid])

    assert {row["event_id"] for row in selected} == {"g1", "g2"}
    assert duplicates == 0
