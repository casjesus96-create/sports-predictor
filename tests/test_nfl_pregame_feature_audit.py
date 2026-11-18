import gzip
import io

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
         "sacks_suffered": "1", "rushing_fumbles_lost": "0",
         "passing_yards": "250", "rushing_yards": "90",
         "passing_tds": "2", "rushing_tds": "1"},
        {"game_id": "g1", "team": "MIA", "passing_epa": "-0.4",
         "rushing_epa": "0.1", "passing_interceptions": "1",
         "sacks_suffered": "2", "rushing_fumbles_lost": "0",
         "passing_yards": "180", "rushing_yards": "110",
         "passing_tds": "1", "rushing_tds": "0"},
        {"game_id": "g2", "team": "BUF", "passing_epa": "0.7",
         "rushing_epa": "0.3", "passing_interceptions": "0",
         "sacks_suffered": "0", "rushing_fumbles_lost": "0",
         "passing_yards": "275", "rushing_yards": "105",
         "passing_tds": "2", "rushing_tds": "1"},
    ]
    pbp_rows = [
        {"game_id": "g1", "posteam": "BUF", "defteam": "MIA",
         "epa": "0.3", "success": "1", "down": "3",
         "third_down_converted": "1", "fourth_down_converted": "0",
         "yards_gained": "12", "pass_touchdown": "0", "rush_touchdown": "0",
         "sack": "0", "interception": "0", "fumble_lost": "0",
         "play_deleted": "0", "aborted_play": "0"},
        {"game_id": "g1", "posteam": "MIA", "defteam": "BUF",
         "epa": "-0.2", "success": "0", "down": "3",
         "third_down_converted": "0", "fourth_down_converted": "0",
         "yards_gained": "5", "pass_touchdown": "0", "rush_touchdown": "0",
         "sack": "0", "interception": "0", "fumble_lost": "0",
         "play_deleted": "0", "aborted_play": "0"},
    ]

    def fake_download(session, url, row_handler=None):
        if "stats_team" in url:
            return team_rows, list(team_rows[0])
        if row_handler is not None:
            for row in pbp_rows:
                row_handler(row)
            return len(pbp_rows), list(pbp_rows[0])
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
    assert features["team_passing_yards"] == 1
    assert features["team_rushing_yards"] == 1
    assert features["team_passing_touchdowns"] == 1
    assert features["team_rushing_touchdowns"] == 1
    assert features["team_sacks_suffered"] == 1
    assert features["pbp_yards_per_play"] == 1
    assert features["pbp_offensive_touchdowns"] == 1
    assert features["pbp_fourth_down_rate"] == 0  # No fourth-down attempts in prior sample
    assert features["pbp_defensive_yards_allowed"] == 1
    assert features["pbp_defensive_sacks"] == 1
    assert features["pbp_defensive_turnovers"] == 1

    profiles = {item["game_id"]: item for item in result["advanced_team_profiles"]}
    # For g2, only g1 is prior; g2 itself and future g3 are excluded.
    buf_before_g2 = profiles["g2"]["teams"]["BUF"]
    assert buf_before_g2["games_sampled"] == 1
    assert buf_before_g2["sample_game_ids"] == ["g1"]
    assert buf_before_g2["passing_yards_per_game"] == 250
    assert buf_before_g2["rushing_yards_per_game"] == 90
    assert buf_before_g2["passing_touchdowns_per_game"] == 2
    assert buf_before_g2["rushing_touchdowns_per_game"] == 1
    assert buf_before_g2["third_down_attempts"] == 1
    assert buf_before_g2["third_down_conversion_rate"] == 1
    assert buf_before_g2["fourth_down_conversion_rate"] is None
    # Defensive profile uses prior plays only and keeps absent denominators null.
    assert buf_before_g2["defensive_yards_allowed_per_play"] == 5
    assert buf_before_g2["passing_epa_per_game"] == 1.2
    assert buf_before_g2["offensive_epa_per_play"] == 0.3
    assert buf_before_g2["offensive_success_rate"] == 1
    assert buf_before_g2["offensive_yards_per_play"] == 12
    assert buf_before_g2["defensive_epa_allowed_per_play"] == -0.2
    assert buf_before_g2["defensive_success_rate_allowed"] == 0
    assert buf_before_g2["offensive_interceptions_per_game"] == 0
    assert buf_before_g2["offensive_fumbles_lost_per_game"] == 0
    assert buf_before_g2["turnovers_per_game"] == 0
    assert buf_before_g2["defensive_sacks_per_game"] == 0
    assert buf_before_g2["defensive_turnovers_per_game"] == 0
    assert result["advanced_team_profile_method"]["read_only"] is True


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


def test_number_rejects_non_finite_and_malformed_metrics():
    assert audit._number({"metric": "1.25"}, "metric") == 1.25
    assert audit._number({"metric": "-0.75"}, "metric") == -0.75
    assert audit._number({"metric": "NaN"}, "metric") is None
    assert audit._number({"metric": "inf"}, "metric") is None
    assert audit._number({"metric": "-Infinity"}, "metric") is None
    assert audit._number({"metric": "not-a-number"}, "metric") is None
    assert audit._number({"metric": ""}, "metric") is None

def test_pregame_audit_reports_schedule_source_failure(monkeypatch):
    def fail_schedule(season):
        raise RuntimeError("schedule source unavailable")

    monkeypatch.setattr(audit, "load_schedule", fail_schedule)
    result = audit.audit_nfl_pregame_feature_coverage(2026, session=object())

    schedule = next(item for item in result["sources"] if item["key"] == "schedule")
    assert schedule["available"] is False
    assert "schedule source unavailable" in schedule["error"]
    assert result["advanced_team_profiles"] == []


def test_pregame_audit_reports_unexpected_stats_source_failure(monkeypatch):
    monkeypatch.setattr(
        audit, "load_schedule",
        lambda season: [_game("g1", "2026-09-01T17:00:00+00:00", "BUF", "MIA", 20, 10)],
    )

    def fail_download(session, url, row_handler=None):
        raise RuntimeError("compressed source could not be decoded")

    monkeypatch.setattr(audit, "_download_rows", fail_download)
    result = audit.audit_nfl_pregame_feature_coverage(2026, session=object())

    weekly = next(item for item in result["sources"] if item["key"] == "weekly_team_stats")
    pbp = next(item for item in result["sources"] if item["key"] == "play_by_play")
    assert weekly["available"] is False
    assert pbp["available"] is False
    assert "could not be decoded" in weekly["error"]
    assert result["success"] is True


def test_download_rows_streams_and_aggregates_without_returning_raw_rows():
    payload = io.BytesIO()
    with gzip.GzipFile(fileobj=payload, mode="wb") as zipped:
        zipped.write(b"game_id,posteam,epa\ng1,BUF,0.5\ng2,MIA,-0.2\n")
    compressed = payload.getvalue()

    class FakeResponse:
        def __init__(self):
            self.raw = io.BytesIO(compressed)
            self.closed = False

        def raise_for_status(self):
            return None

        def close(self):
            self.closed = True

    class FakeSession:
        def get(self, url, timeout, stream=False):
            assert stream is True
            self.response = FakeResponse()
            return self.response

    seen = []
    session = FakeSession()
    row_count, columns = audit._download_rows(
        session, "https://example.test/sample.csv.gz",
        row_handler=lambda row: seen.append(row["game_id"]),
    )

    assert row_count == 2
    assert columns == ["game_id", "posteam", "epa"]
    assert seen == ["g1", "g2"]
    assert session.response.closed is True
