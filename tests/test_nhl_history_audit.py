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
