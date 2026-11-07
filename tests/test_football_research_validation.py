from datetime import date, timedelta

from football_research_validation import build_candidate_validation


def _row(index, season, actual="home"):
    base = {"home": 0.40, "draw": 0.30, "away": 0.30}
    candidate = {"home": 0.70, "draw": 0.15, "away": 0.15}
    if actual == "draw":
        base = {"home": 0.30, "draw": 0.40, "away": 0.30}
        candidate = {"home": 0.15, "draw": 0.70, "away": 0.15}
    elif actual == "away":
        base = {"home": 0.30, "draw": 0.30, "away": 0.40}
        candidate = {"home": 0.15, "draw": 0.15, "away": 0.70}
    return {
        "match_id": str(index),
        "season": season,
        "kickoff_at": f"{date(2000, 1, 1) + timedelta(days=index // 2)}T00:00:00+00:00",
        "home_team": f"Home {index}",
        "away_team": f"Away {index}",
        "actual_outcome": actual,
        "base": base,
        "candidate": candidate,
    }


def test_validation_uses_chronological_final_holdout_and_season_breakdown():
    rows = []
    for index in range(500):
        season = f"S{index // 125 + 1}"
        actual = ("home", "draw", "away")[index % 3]
        rows.append(_row(index, season, actual))
    evaluation = {
        "per_match": rows,
        "advanced_goals_shadow_per_match": [
            {**row, "advanced_shadow": row["candidate"]} for row in rows
        ],
    }

    result = build_candidate_validation(evaluation)
    assert result["protocol"] == "chronological_holdout_cluster_bootstrap_v2"
    assert result["split"]["development_matches"] == 400
    assert result["split"]["holdout_matches"] == 100
    assert result["split"]["holdout_start"] == rows[400]["kickoff_at"]
    assert len(result["season_breakdown"]) == 4
    h2h = result["candidates"]["h2h"]
    assert h2h["holdout"]["sample_size"] == 100
    assert h2h["holdout"]["brier_delta"]["ci_95"][1] < 0
    assert h2h["holdout"]["log_loss_delta"]["ci_95"][1] < 0
    assert h2h["gate"]["status"] == "APTO_PARA_REVISION"
    assert h2h["gate"]["season_consistency_scope"] == "development_only"
    assert h2h["gate"]["automatic_activation"] is False


def test_holdout_seasons_cannot_satisfy_development_season_minimum():
    rows = [
        _row(index, "S1" if index < 200 else "S2" if index < 400 else "S3")
        for index in range(500)
    ]
    result = build_candidate_validation({"per_match": rows})
    gate = result["candidates"]["h2h"]["gate"]
    assert result["split"]["holdout_matches"] == 100
    assert gate["eligible_seasons"] == 2
    assert gate["season_consistency_scope"] == "development_only"
    assert [row["season"] for row in result["season_breakdown"]] == ["S1", "S2"]
    assert result["holdout_season_diagnostics"][0]["season"] == "S3"
    assert gate["status"] == "MUESTRA_INSUFICIENTE"


def test_validation_refuses_small_holdout_and_missing_seasons():
    rows = [_row(index, "S1") for index in range(30)]
    result = build_candidate_validation({"per_match": rows})
    gate = result["candidates"]["h2h"]["gate"]
    assert result["split"]["holdout_matches"] == 6
    assert gate["status"] == "MUESTRA_INSUFICIENTE"
    assert gate["automatic_activation"] is False
    assert gate["reasons"]


def test_validation_bootstrap_is_deterministic_and_clustered_by_date():
    rows = [_row(index, f"S{index // 100}") for index in range(500)]
    first = build_candidate_validation({"per_match": rows})
    second = build_candidate_validation({"per_match": rows})
    first_interval = first["candidates"]["h2h"]["holdout"]["brier_delta"]
    second_interval = second["candidates"]["h2h"]["holdout"]["brier_delta"]
    assert first_interval == second_interval
    assert first_interval["cluster_count"] < first_interval["n"]
    assert first["uncertainty"]["cluster_unit"].startswith("Fecha calendario")


def test_validation_requires_enough_independent_holdout_dates():
    rows = [_row(index, f"S{index // 125}") for index in range(500)]
    for row in rows[400:]:
        row["kickoff_at"] = "2026-11-01T12:00:00+00:00"
    result = build_candidate_validation({"per_match": rows})
    gate = result["candidates"]["h2h"]["gate"]
    assert gate["holdout_clusters"] == 1
    assert gate["holdout_cluster_minimum"] == 20
    assert gate["status"] == "MUESTRA_INSUFICIENTE"



def test_goal_markets_use_same_chronological_holdout_and_paired_losses():
    rows = []
    for index in range(500):
        row = _row(index, f"S{index // 125}")
        actual_btts = index % 2 == 0
        actual_over = index % 3 != 0
        row["markets"] = {
            "btts_yes": {
                "base": 0.50, "candidate": 0.90 if actual_btts else 0.10,
                "actual": actual_btts,
            },
            "over_2_5": {
                "base": 0.50, "candidate": 0.90 if actual_over else 0.10,
                "actual": actual_over,
            },
        }
        row["actual_home_goals"] = 2
        row["actual_away_goals"] = 1
        row["actual_total_goals"] = 3
        row["base_expected_goals"] = {"home": 1.0, "away": 1.0, "total": 2.0}
        row["candidate_expected_goals"] = {"home": 1.8, "away": 1.1, "total": 2.9}
        rows.append(row)

    result = build_candidate_validation({
        "per_match": [_row(index, f"S{index // 125}") for index in range(500)],
        "goal_market_per_match": rows,
    })
    markets = result["goal_markets"]
    assert markets["status"] == "DESCRIPTIVE_RESEARCH_ONLY"
    assert markets["development_sample_size"] == 400
    assert markets["holdout_sample_size"] == 100
    btts = markets["markets"]["btts_yes"]["holdout"]
    assert btts["sample_size"] == 100
    assert btts["candidate_brier"] < btts["base_brier"]
    assert btts["candidate_log_loss"] < btts["base_log_loss"]
    assert btts["brier_delta"]["ci_95"][1] < 0
    assert markets["expected_goals_mae"]["holdout"]["total"]["delta_mae"] < 0
    assert markets["automatic_activation"] is False



def test_goal_market_reliability_is_descriptive_and_reports_empty_bins():
    rows = []
    for index in range(500):
        row = _row(index, f"S{index // 125}")
        position = index % 10
        probability = 0.80 if position < 5 else 0.20
        actual = position < 4 or position == 5
        row["markets"] = {
            "btts_yes": {
                "base": 0.50,
                "candidate": probability,
                "actual": actual,
            }
        }
        row["actual_home_goals"] = 1
        row["actual_away_goals"] = 1 if actual else 0
        row["actual_total_goals"] = 2 if actual else 1
        row["base_expected_goals"] = {"home": 1.0, "away": 1.0, "total": 2.0}
        row["candidate_expected_goals"] = {"home": 1.0, "away": 1.0, "total": 2.0}
        rows.append(row)

    result = build_candidate_validation({
        "per_match": [_row(index, f"S{index // 125}") for index in range(500)],
        "goal_market_per_match": rows,
    })
    reliability = result["goal_markets"]["markets"]["btts_yes"]["holdout"]["reliability"]
    assert reliability["base"]["sample_size"] == 100
    assert reliability["candidate"]["sample_size"] == 100
    assert reliability["candidate"]["ece"] < reliability["base"]["ece"]
    assert len(reliability["candidate"]["bins"]) == 5
    assert any(bucket["n"] == 0 for bucket in reliability["candidate"]["bins"])
    assert all(
        bucket["mean_predicted_probability"] is None
        for bucket in reliability["candidate"]["bins"] if bucket["n"] == 0
    )


def test_binary_reliability_handles_empty_and_boundary_probabilities():
    from football_research_validation import _binary_reliability

    empty = _binary_reliability([], [])
    assert empty["sample_size"] == 0
    assert empty["ece"] is None
    result = _binary_reliability([0.0, 1.0], [0.0, 1.0])
    assert result["ece"] == 0
    assert result["bins"][0]["n"] == 1
    assert result["bins"][-1]["n"] == 1
