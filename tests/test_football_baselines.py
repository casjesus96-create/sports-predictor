from datetime import date, timedelta

from football_baselines import build_baseline_comparison
from football_model import MODEL_VERSION


def archive_history():
    rows = []
    start = date(2023, 1, 1)
    for index in range(10):
        day = (start + timedelta(days=index)).isoformat()
        rows.append({
            "match_date": day, "home_team": "Alpha", "home_team_key": "alpha",
            "away_team": f"Club {index}", "away_team_key": f"club-{index}",
            "home_score": 2 if index % 2 else 1, "away_score": 0 if index % 2 else 1,
        })
    for index in range(10):
        day = (start + timedelta(days=10 + index)).isoformat()
        rows.append({
            "match_date": day, "home_team": f"Opponent {index}", "home_team_key": f"opponent-{index}",
            "away_team": "Beta", "away_team_key": "beta",
            "home_score": 0 if index % 2 else 1, "away_score": 1 if index % 2 else 2,
        })
    for index in range(40):
        day = (start + timedelta(days=20 + index)).isoformat()
        rows.append({
            "match_date": day, "home_team": f"League Home {index}", "home_team_key": f"league-home-{index}",
            "away_team": f"League Away {index}", "away_team_key": f"league-away-{index}",
            "home_score": index % 4, "away_score": (index + 1) % 3,
        })
    return rows


def snapshots(count=15):
    rows = []
    for index in range(count):
        day = date(2026, 1, 1) + timedelta(days=index)
        home_score, away_score = ((2, 0) if index % 3 == 0 else (1, 1) if index % 3 == 1 else (0, 2))
        actual = "HOME" if home_score > away_score else "AWAY" if home_score < away_score else "DRAW"
        rows.append({
            "provider_match_id": index + 1,
            "competition_code": "PL",
            "kickoff_at": f"{day.isoformat()}T15:00:00Z",
            "home_team": "Alpha",
            "away_team": "Beta",
            "model_version": MODEL_VERSION,
            "home_probability": 0.60,
            "draw_probability": 0.22,
            "away_probability": 0.18,
            "prediction_payload": {
                "goal_markets": {
                    "both_teams_to_score": {"yes": {"probability": 0.62}},
                    "total_goals": {"over_2_5": {"probability": 0.57}},
                }
            },
            "result_status": "SETTLED",
            "actual_home_score": home_score,
            "actual_away_score": away_score,
            "actual_outcome": actual,
        })
    return rows


def test_baseline_comparison_uses_official_snapshots_and_paired_samples():
    report = build_baseline_comparison(snapshots(), archive_history(), "PL", "Europe/London")

    assert report["success"] is True
    assert report["read_only"] is True
    assert report["model_version"] == MODEL_VERSION
    assert report["model_changed"] is False
    assert report["provider_calls"] == 0
    assert report["snapshots_written"] == 0
    assert report["split"]["development_matches"] == 12
    assert report["split"]["holdout_matches"] == 3
    assert report["development"]["paired_1x2_sample_size"] == 12
    assert report["holdout"]["paired_1x2_sample_size"] == 3
    assert report["development"]["one_x_two"]["official_model"]["sample_size"] == 12
    assert report["development"]["one_x_two"]["league_frequency_baseline"]["sample_size"] == 12
    assert report["development"]["one_x_two"]["recent_form_baseline"]["sample_size"] == 12
    assert report["development"]["markets"]["btts_yes"]["sample_size"] == 12
    assert report["development"]["markets"]["over_2_5"]["sample_size"] == 12


def test_holdout_baseline_is_frozen_before_holdout_and_ignores_holdout_results():
    base = build_baseline_comparison(snapshots(), archive_history(), "PL", "Europe/London")
    contaminated_archive = archive_history()
    for index in range(30):
        contaminated_archive.append({
            "match_date": (date(2026, 1, 13) + timedelta(days=index)).isoformat(),
            "home_team": "Alpha", "home_team_key": "alpha",
            "away_team": "Beta", "away_team_key": "beta",
            "home_score": 0, "away_score": 5,
        })
    contaminated = build_baseline_comparison(
        snapshots(), contaminated_archive, "PL", "Europe/London"
    )

    assert base["split"]["holdout_start_local_date"] == "2026-01-13"
    assert contaminated["holdout"]["one_x_two"]["league_frequency_baseline"] == base["holdout"]["one_x_two"]["league_frequency_baseline"]
    assert contaminated["holdout"]["one_x_two"]["recent_form_baseline"] == base["holdout"]["one_x_two"]["recent_form_baseline"]


def test_same_local_calendar_day_is_never_split_between_development_and_holdout():
    rows = snapshots(10)
    rows[8]["kickoff_at"] = rows[7]["kickoff_at"]
    report = build_baseline_comparison(rows, archive_history(), "PL", "Europe/London")

    assert report["split"]["development_matches"] == 9
    assert report["split"]["holdout_matches"] == 1


def test_insufficient_historical_coverage_excludes_unpaired_targets():
    report = build_baseline_comparison(snapshots(), [], "PL", "Europe/London")

    assert report["snapshot_sample_size"] == 15
    assert report["development"]["official_valid_targets"] == 12
    assert report["development"]["league_baseline_eligible_targets"] == 0
    assert report["development"]["recent_form_baseline_eligible_targets"] == 0
    assert report["development"]["paired_1x2_sample_size"] == 0
    assert report["development"]["one_x_two"]["official_model"]["brier_score"] is None


def test_invalid_or_timezone_naive_snapshots_are_excluded():
    rows = snapshots(3)
    rows[0]["kickoff_at"] = "2026-01-01T15:00:00"
    rows[1]["home_probability"] = 1.4
    rows[2]["model_version"] = "EXPERIMENTAL"
    report = build_baseline_comparison(rows, archive_history(), "PL", "Europe/London")

    assert report["snapshot_sample_size"] == 0
    assert report["excluded_invalid_snapshots"] == 3
    assert report["development"]["official_valid_targets"] == 0
    assert report["read_only"] is True


def test_local_competition_date_is_used_for_archive_cutoffs():
    rows = snapshots(2)
    rows[0]["kickoff_at"] = "2026-01-01T23:30:00Z"
    rows[1]["kickoff_at"] = "2026-01-03T00:00:00Z"
    report = build_baseline_comparison(rows, archive_history(), "PL", "Europe/Paris")

    assert report["split"]["development_matches"] == 1
    assert report["split"]["holdout_start_local_date"] == "2026-01-02"



def test_baseline_endpoint_reads_official_snapshots_and_owned_archive(monkeypatch):
    import football_learning

    captured = []
    snapshot_rows = snapshots()
    archive_rows = archive_history()

    class Query:
        def __init__(self, table):
            self.table_name = table
            self.offset = 0
            self.limit = 1000
            self.filters = []
        def select(self, columns):
            return self
        def eq(self, column, value):
            self.filters.append((column, value))
            return self
        def order(self, column, desc=False):
            self.ordering = (column, desc)
            return self
        def range(self, start, end):
            self.offset, self.limit = start, end - start + 1
            return self
        def execute(self):
            captured.append((self.table_name, self.filters, self.ordering))
            source = snapshot_rows if self.table_name == "football_prediction_snapshots" else archive_rows
            return type("Result", (), {"data": source[self.offset:self.offset + self.limit]})()

    class Client:
        def table(self, name):
            return Query(name)

    monkeypatch.setattr(football_learning, "get_supabase_client", lambda: Client())
    report = football_learning.football_baseline_comparison("PL")

    assert report["success"] is True
    assert report["provider_calls"] == 0
    assert report["model_changed"] is False
    assert {item[0] for item in captured} == {"football_prediction_snapshots", "football_match_archive"}
    snapshot_filters = next(item[1] for item in captured if item[0] == "football_prediction_snapshots")
    assert ("competition_code", "PL") in snapshot_filters
    assert ("model_version", MODEL_VERSION) in snapshot_filters
    assert ("result_status", "SETTLED") in snapshot_filters


def test_baseline_endpoint_rejects_unsupported_competition():
    import pytest
    from fastapi import HTTPException
    import football_learning

    with pytest.raises(HTTPException) as error:
        football_learning.football_baseline_comparison("XYZ")
    assert error.value.status_code == 400
