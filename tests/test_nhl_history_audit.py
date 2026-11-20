import nhl_history_audit as audit


def _game(game_id="2025020001", home="TOR", away="BOS", home_score=3, away_score=2):
    return {
        "game_id": game_id,
        "game_date": "2025-10-08",
        "game_state": "OFF",
        "completed": True,
        "game_type": 2,
        "home": {"abbreviation": home, "score": home_score},
        "away": {"abbreviation": away, "score": away_score},
    }


def test_report_deduplicates_and_confirms_games_from_both_team_schedules():
    game = _game()
    report = audit.build_season_coverage_report(
        "20252026",
        ["TOR", "BOS"],
        {"TOR": {"games": [game]}, "BOS": {"games": [game]}},
    )
    assert report["success"] is True
    assert report["unique_games"] == 1
    assert report["schedule_observations"] == 2
    assert report["duplicate_observations"] == 1
    assert report["games_seen_from_multiple_team_schedules"] == 1
    assert report["cross_team_confirmation_rate"] == 1.0
    assert report["persistence"] == "read_only_no_database_writes"


def test_report_flags_conflicting_duplicate_game_facts():
    report = audit.build_season_coverage_report(
        "20252026",
        ["TOR", "BOS"],
        {
            "TOR": {"games": [_game(home_score=3)]},
            "BOS": {"games": [_game(home_score=4)]},
        },
    )
    assert report["success"] is False
    assert report["identity_conflicts"][0]["game_id"] == "2025020001"


def test_report_flags_completed_game_without_both_scores():
    report = audit.build_season_coverage_report(
        "20252026",
        ["TOR"],
        {"TOR": {"games": [_game(away_score=None)]}},
    )
    assert report["success"] is False
    assert report["completed_games_missing_score"] == ["2025020001"]


def test_report_flags_wrong_team_membership():
    report = audit.build_season_coverage_report(
        "20252026",
        ["TOR"],
        {"TOR": {"games": [_game(home="MTL", away="BOS")]}},
    )
    assert report["success"] is False
    assert report["invalid_team_membership"] == [{"requested_team": "TOR", "game_id": "2025020001"}]


def test_audit_continues_after_one_team_source_failure(monkeypatch):
    def fake_schedule(team, season):
        if team == "BOS":
            raise audit.NHLDataError("source unavailable")
        return {"games": [_game()]}

    monkeypatch.setattr(audit, "get_team_season_schedule", fake_schedule)
    report = audit.audit_nhl_season("20252026", ["TOR", "BOS"])
    assert report["teams_succeeded"] == 1
    assert report["teams_failed"] == 1
    assert report["team_failures"] == {"BOS": "source unavailable"}
    assert report["success"] is False


def test_report_fails_when_requested_team_response_is_missing():
    report = audit.build_season_coverage_report(
        "20252026",
        ["TOR", "BOS"],
        {"TOR": {"games": [_game()]}},
    )
    assert report["success"] is False
    assert report["missing_team_responses"] == ["BOS"]


def test_markdown_summary_exposes_coverage_and_read_only_scope():
    report = audit.build_season_coverage_report(
        "20252026",
        ["TOR", "BOS"],
        {"TOR": {"games": [_game()]}, "BOS": {"games": [_game()]}},
    )
    summary = audit.render_markdown_summary(report)
    assert "NHL historical coverage" in summary
    assert "Unique games" in summary
    assert "read-only" in summary


def test_report_breaks_down_game_types_and_states_once_per_unique_game():
    preseason = _game(game_id="2025010001")
    preseason["game_type"] = 1
    preseason["game_state"] = "OFF"
    regular = _game(game_id="2025020002")
    regular["game_type"] = 2
    regular["game_state"] = "FUT"
    report = audit.build_season_coverage_report(
        "20252026",
        ["TOR", "BOS"],
        {
            "TOR": {"games": [preseason, regular]},
            "BOS": {"games": [preseason, regular]},
        },
    )
    assert report["game_type_counts"] == {"1": 1, "2": 1}
    assert report["game_state_counts"] == {"FUT": 1, "OFF": 1}


def test_report_fails_closed_when_game_type_is_missing():
    game = _game()
    game["game_type"] = None
    report = audit.build_season_coverage_report(
        "20252026", ["TOR"], {"TOR": {"games": [game]}}
    )
    assert report["success"] is False
    assert report["games_missing_game_type"] == ["2025020001"]

 
def test_report_lists_games_without_cross_team_confirmation():
    game = _game(game_id="2024020999")
    report = audit.build_season_coverage_report(
        "20242025",
        ["TOR", "BOS"],
        {"TOR": {"games": [game]}, "BOS": {"games": []}},
    )
    assert report["success"] is True
    assert report["review_required"] is True
    assert report["games_without_cross_team_confirmation"] == [{
        "game_id": "2024020999",
        "game_date": "2025-10-08",
        "home_team": "TOR",
        "away_team": "BOS",
        "home_score": 3,
        "away_score": 2,
        "game_state": "OFF",
        "game_type": 2,
        "observed_teams": ["TOR"],
        "missing_team": "BOS",
    }]


def test_report_lists_non_completed_games_with_identity():
    game = _game(game_id="2024021000")
    game["game_state"] = "FUT"
    game["completed"] = False
    report = audit.build_season_coverage_report(
        "20242025", ["TOR"], {"TOR": {"games": [game]}}
    )
    assert report["non_completed_games"] == [{
        "game_id": "2024021000",
        "game_date": "2025-10-08",
        "home_team": "TOR",
        "away_team": "BOS",
        "home_score": 3,
        "away_score": 2,
        "game_state": "FUT",
        "game_type": 2,
    }]
    assert report["review_required"] is True


def test_review_required_is_false_when_all_games_are_confirmed_and_completed():
    game = _game()
    report = audit.build_season_coverage_report(
        "20252026",
        ["TOR", "BOS"],
        {"TOR": {"games": [game]}, "BOS": {"games": [game]}},
    )
    assert report["review_required"] is False
