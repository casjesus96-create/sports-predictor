import nfl_pregame_feature_audit as audit


def _game(game_id, kickoff, home, away, hs=None, aws=None):
    return {
        "game_id": game_id, "kickoff": kickoff, "game_type": "REG",
        "home": home, "away": away, "home_score": hs, "away_score": aws,
    }


def test_pregame_audit_excludes_same_game_and_future_games(monkeypatch):
    games = [
        _game("g1", "2026-09-01T17:00:00+00:00", "BUF", "MIA", 20, 10),
        _game("g2", "2026-09-08T17:00:00+00:00", "BUF", "NYJ", 24, 17),
        _game("g3", "2026-09-15T17:00:00+00:00", "MIA", "BUF", None, None),
    ]
    monkeypatch.setattr(audit, "load_schedule", lambda season: games)

    team_rows = [
        {"game_id": "g1", "team": "BUF", "passing_epa": "1.2",
         "rushing_epa": "0.2", "passing_interceptions": "0",
         "sacks_suffered": "1", "rushing_fumbles_lost": "0"},
        {"game_id": "g1", "team": "MIA", "passing_epa": "-0.4",
         "rushing_epa": "0.1", "passing_interceptions": "1",
         "sacks_suffered": "2", "rushing_fumbles_lost": "0"},
        {"game_id": "g2", "team": "BUF", "passing_epa": "0.7",
         "rushing_epa": "0.3", "passing_interceptions": "0",
         "sacks_suffered": "0", "rushing_fumbles_lost": "0"},
    ]
    pbp_rows = [
        {"game_id": "g1", "posteam": "BUF", "defteam": "MIA",
         "epa": "0.3", "success": "1", "down": "3",
         "third_down_converted": "1", "play_deleted": "0", "aborted_play": "0"},
        {"game_id": "g1", "posteam": "MIA", "defteam": "BUF",
         "epa": "-0.2", "success": "0", "down": "3",
         "third_down_converted": "0", "play_deleted": "0", "aborted_play": "0"},
    ]

    def fake_download(session, url):
        if "stats_team" in url:
            return team_rows, list(team_rows[0])
        return pbp_rows, list(pbp_rows[0])

    monkeypatch.setattr(audit, "_download_rows", fake_download)
    result = audit.audit_nfl_pregame_feature_coverage(2026, session=object())

    assert result["read_only"] is True
    assert result["model_impact"] == "none"
    assert result["target_games"] == 3
    assert result["completed_games_available_for_join"] == 2
    thresholds = {x["minimum_prior_games_per_team"]: x["games_with_both_teams"]
                  for x in result["history_depth"]}
    assert thresholds[1] == 1
    assert thresholds[3] == 0
    assert thresholds[5] == 0
    features = {x["feature"]: x["games_with_both_teams"]
                for x in result["candidate_feature_coverage"]}
    assert features["team_passing_epa"] == 1
    assert features["pbp_offensive_epa"] == 1


def test_pregame_audit_handles_no_target_games(monkeypatch):
    monkeypatch.setattr(audit, "load_schedule", lambda season: [])
    monkeypatch.setattr(
        audit, "_download_rows",
        lambda session, url: ([], ["game_id", "team"]),
    )
    result = audit.audit_nfl_pregame_feature_coverage(2026, session=object())
    assert result["target_games"] == 0
    assert all(item["coverage_pct"] == 0 for item in result["history_depth"])
    assert all(item["coverage_pct"] == 0
               for item in result["candidate_feature_coverage"])
