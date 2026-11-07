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
                "base": 0.70,
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



def test_goal_market_season_breakdown_uses_development_only_and_marks_small_samples():
    rows = []
    for index in range(500):
        row = _row(index, f"S{index // 125 + 1}")
        actual = index % 2 == 0
        row["markets"] = {
            "btts_yes": {"base": 0.50, "candidate": 0.60, "actual": actual},
            "over_2_5": {"base": 0.45, "candidate": 0.55, "actual": actual},
        }
        row["actual_home_goals"] = 1
        row["actual_away_goals"] = 1 if actual else 0
        row["actual_total_goals"] = 2 if actual else 1
        row["base_expected_goals"] = {"home": 1.0, "away": 1.0, "total": 2.0}
        row["candidate_expected_goals"] = {"home": 1.0, "away": 1.0, "total": 2.0}
        rows.append(row)

    result = build_candidate_validation({
        "per_match": [_row(index, f"S{index // 125 + 1}") for index in range(500)],
        "goal_market_per_match": rows,
    })
    goals = result["goal_markets"]
    breakdown = goals["development_season_breakdown"]
    assert goals["season_diagnostics_scope"] == "development_only"
    assert sum(item["sample_size"] for item in breakdown) == goals["development_sample_size"] == 400
    assert [item["season"] for item in breakdown] == ["S1", "S2", "S3", "S4"]
    assert breakdown[-1]["sample_size"] == 25
    assert breakdown[-1]["markets"]["btts_yes"]["eligible_for_descriptive_comparison"] is False
    assert breakdown[0]["markets"]["btts_yes"]["eligible_for_descriptive_comparison"] is True
    assert goals["holdout_sample_size"] == 100



def test_binary_reliability_handles_empty_and_boundary_probabilities():
    from football_research_validation import _binary_reliability

    empty = _binary_reliability([], [])
    assert empty["sample_size"] == 0
    assert empty["ece"] is None
    result = _binary_reliability([0.0, 1.0], [0.0, 1.0])
    assert result["ece"] == 0
    assert result["bins"][0]["n"] == 1
    assert result["bins"][-1]["n"] == 1



def test_goal_market_temporal_windows_are_chronological_clustered_and_development_only():
    goal_rows = []
    for index in range(500):
        row = _row(index, f"S{index // 125 + 1}")
        row["kickoff_at"] = _row(index, f"S{index // 125 + 1}")["kickoff_at"]
        row["actual_home_goals"] = 1
        row["actual_away_goals"] = 1
        row["actual_total_goals"] = 2
        row["base_expected_goals"] = {"home": 1.2, "away": 0.9, "total": 2.1}
        row["candidate_expected_goals"] = {"home": 1.1, "away": 1.0, "total": 2.1}
        actual = index % 2 == 0
        row["markets"] = {
            "btts_yes": {"base": 0.50, "candidate": 0.55, "actual": actual},
            "over_2_5": {"base": 0.45, "candidate": 0.50, "actual": actual},
        }
        goal_rows.append(row)

    duplicated_dates = []
    for row in goal_rows[:12]:
        duplicate = dict(row)
        duplicate["match_id"] = f"duplicate-{row['match_id']}"
        duplicated_dates.append(duplicate)
    goal_rows.extend(duplicated_dates)

    result = build_candidate_validation({
        "per_match": [_row(index, f"S{index // 125 + 1}") for index in range(500)],
        "goal_market_per_match": goal_rows,
    })
    temporal = result["goal_markets"]["temporal_drift"]
    assert temporal["scope"] == "development_only"
    assert temporal["window_count"] >= 2
    windows = temporal["windows"]
    assert all(windows[index]["date_end"] < windows[index + 1]["date_start"] for index in range(len(windows) - 1))
    assert sum(window["sample_size"] for window in windows) == result["goal_markets"]["development_sample_size"]
    assert all(window["independent_dates"] >= 10 for window in windows)
    assert all(
        window["markets"]["btts_yes"]["sample_size"] == window["sample_size"]
        for window in windows
    )
    assert result["goal_markets"]["holdout_sample_size"] == 100


def test_goal_market_temporal_windows_report_insufficient_sample_without_fabrication():
    from football_research_validation import _goal_market_temporal_breakdown

    result = _goal_market_temporal_breakdown([], ("btts_yes", "over_2_5"))
    assert result["window_count"] == 0
    assert result["windows"] == []
    assert "insuficiente" in result["reason"].lower()


def test_1x2_temporal_drift_is_clustered_development_only_and_reports_each_outcome():
    rows = []
    advanced_rows = []
    for index in range(500):
        actual = ("home", "draw", "away")[index % 3]
        row = _row(index, f"S{index // 125 + 1}", actual)
        rows.append(row)
        advanced_rows.append({
            **row,
            "advanced_shadow": {
                "home": 0.45, "draw": 0.30, "away": 0.25,
            },
        })

    result = build_candidate_validation({
        "per_match": rows,
        "advanced_goals_shadow_per_match": advanced_rows,
    })
    drift = result["temporal_drift_1x2"]
    assert drift["scope"] == "development_only"
    for candidate_key in ("h2h", "advanced_goals"):
        candidate = drift[candidate_key]
        assert candidate["scope"] == "development_only"
        assert candidate["window_count"] >= 2
        windows = candidate["windows"]
        assert sum(window["sample_size"] for window in windows) == 400
        assert all(
            windows[index]["date_end"] < windows[index + 1]["date_start"]
            for index in range(len(windows) - 1)
        )
        assert windows[-1]["date_end"] < result["split"]["holdout_start"][:10]
        for window in windows:
            assert window["independent_dates"] >= 10
            assert window["eligible_for_descriptive_comparison"] is True
            assert window["base_accuracy"] is not None
            assert window["candidate_accuracy"] is not None
            assert set(window["outcomes"]) == {"home", "draw", "away"}
            for outcome in ("home", "draw", "away"):
                assert window["outcomes"][outcome]["base"]["sample_size"] == window["sample_size"]
                assert window["outcomes"][outcome]["candidate"]["sample_size"] == window["sample_size"]
                assert len(window["outcomes"][outcome]["base"]["bins"]) == 5
                assert len(window["outcomes"][outcome]["candidate"]["bins"]) == 5


def test_1x2_temporal_drift_reports_insufficient_sample_without_windows():
    from football_research_validation import _multiclass_temporal_breakdown

    result = _multiclass_temporal_breakdown([], "candidate", 123)
    assert result["scope"] == "development_only"
    assert result["window_count"] == 0
    assert result["windows"] == []
    assert "insuficiente" in result["reason"].lower()

def test_reliability_reports_deterministic_date_cluster_bootstrap_intervals():
    from football_research_validation import _binary_reliability

    probabilities = []
    observed = []
    dates = []
    for day in range(30):
        for match in range(4):
            probabilities.append(0.2 + (match % 3) * 0.25)
            observed.append(1.0 if (day + match) % 3 == 0 else 0.0)
            dates.append(f"2025-01-{day + 1:02d}")

    first = _binary_reliability(
        probabilities, observed, cluster_keys=dates, seed=987
    )
    second = _binary_reliability(
        probabilities, observed, cluster_keys=dates, seed=987
    )
    assert first == second
    assert first["uncertainty_cluster_count"] == 30
    assert first["bootstrap_replicates"] == 1000
    assert first["ece_ci_95"] is not None
    assert 0.0 <= first["ece_ci_95"][0] <= first["ece_ci_95"][1] <= 1.0
    assert all(
        bucket["observed_rate_ci_95"] is None
        or 0.0 <= bucket["observed_rate_ci_95"][0] <= bucket["observed_rate_ci_95"][1] <= 1.0
        for bucket in first["bins"]
    )


def test_reliability_with_one_independent_date_does_not_claim_confidence_interval():
    from football_research_validation import _binary_reliability

    result = _binary_reliability(
        [0.2, 0.4, 0.6], [0.0, 1.0, 1.0],
        cluster_keys=["2025-01-01"] * 3,
    )
    assert result["uncertainty_cluster_count"] == 1
    assert result["ece_ci_95"] is None
    assert result["bootstrap_replicates"] == 0

def test_1x2_holdout_reports_one_vs_rest_reliability_with_date_cluster_intervals():
    rows = []
    advanced_rows = []
    for index in range(600):
        actual = ("home", "draw", "away")[index % 3]
        row = _row(index, f"S{index // 200 + 1}", actual)
        rows.append(row)
        advanced_rows.append({
            **row,
            "advanced_shadow": {
                "home": 0.45, "draw": 0.30, "away": 0.25,
            },
        })

    result = build_candidate_validation({
        "per_match": rows,
        "advanced_goals_shadow_per_match": advanced_rows,
    })
    assert result["split"]["holdout_matches"] == 120
    for candidate_key in ("h2h", "advanced_goals"):
        holdout = result["candidates"][candidate_key]["holdout"]
        assert holdout["reliability_scope"] == "holdout_only"
        assert holdout["sample_size"] == 120
        assert holdout["base_accuracy"] is not None
        assert holdout["candidate_accuracy"] is not None
        assert set(holdout["outcomes"]) == {"home", "draw", "away"}
        for outcome in ("home", "draw", "away"):
            base = holdout["outcomes"][outcome]["base"]
            candidate = holdout["outcomes"][outcome]["candidate"]
            assert base["sample_size"] == 120
            assert candidate["sample_size"] == 120
            assert base["uncertainty_cluster_count"] >= 20
            assert candidate["uncertainty_cluster_count"] >= 20
            assert base["bootstrap_replicates"] == 1000
            assert candidate["bootstrap_replicates"] == 1000
            assert base["ece_ci_95"] is not None
            assert candidate["ece_ci_95"] is not None
            assert candidate["ece_ci_95"][0] <= candidate["ece_ci_95"][1]
    assert result["temporal_drift_1x2"]["scope"] == "development_only"


def test_1x2_calibration_bias_is_development_only_and_identifies_over_underprediction():
    rows = []
    advanced_rows = []
    for index in range(600):
        actual = ("home", "draw", "away")[index % 3]
        row = _row(index, f"S{index // 200 + 1}", actual)
        row["base"] = {"home": 0.50, "draw": 0.25, "away": 0.25}
        row["candidate"] = {"home": 0.45, "draw": 0.30, "away": 0.25}
        rows.append(row)
        advanced_rows.append({
            **row,
            "advanced_shadow": {"home": 0.40, "draw": 0.30, "away": 0.30},
        })

    result = build_candidate_validation({
        "per_match": rows,
        "advanced_goals_shadow_per_match": advanced_rows,
    })
    bias = result["calibration_bias_1x2"]
    assert bias["scope"] == "development_only"
    assert bias["automatic_recalibration"] is False
    assert bias["overall"]["h2h"]["sample_size"] == 480
    assert bias["overall"]["advanced_goals"]["sample_size"] == 480

    home = bias["overall"]["h2h"]["outcomes"]["home"]
    draw = bias["overall"]["h2h"]["outcomes"]["draw"]
    assert home["base"]["bias"] > 0
    assert home["base"]["interpretation"] == "SOBREESTIMACION"
    assert home["base"]["bias_ci_95"][0] > 0
    assert draw["base"]["bias"] < 0
    assert draw["base"]["interpretation"] == "SUBESTIMACION"

    assert sum(item["sample_size"] for item in bias["by_season"]) == 480
    assert all(item["eligible_for_descriptive_comparison"] for item in bias["by_season"])
    assert result["split"]["holdout_matches"] == 120
    temporal_windows = result["temporal_drift_1x2"]["h2h"]["windows"]
    assert temporal_windows
    assert result["split"]["holdout_start"][:10] > max(
        window["date_end"] for window in temporal_windows
    )


def test_1x2_calibration_bias_reports_insufficient_ci_and_empty_samples_safely():
    from football_research_validation import _calibration_bias_summary

    empty = _calibration_bias_summary([], "candidate", 10)
    assert empty["sample_size"] == 0
    assert empty["outcomes"] == {}

    rows = [_row(index, "S1") for index in range(3)]
    for row in rows:
        row["kickoff_at"] = "2026-01-01T00:00:00Z"
    result = _calibration_bias_summary(rows, "candidate", 11)
    assert result["independent_dates"] == 1
    assert result["outcomes"]["home"]["base"]["bias"] is not None
    assert result["outcomes"]["home"]["base"]["bias_ci_95"] is None
    assert result["outcomes"]["home"]["base"]["interpretation"] == "IC95_NO_ESTIMABLE"


def test_1x2_calibration_bias_temporal_windows_match_development_dates_only():
    rows = []
    for index in range(700):
        actual = ("home", "draw", "away")[index % 3]
        row = _row(index, f"S{index // 175 + 1}", actual)
        row["base"] = {"home": 0.50, "draw": 0.25, "away": 0.25}
        row["candidate"] = {"home": 0.45, "draw": 0.30, "away": 0.25}
        rows.append(row)

    result = build_candidate_validation({"per_match": rows})
    bias = result["calibration_bias_1x2"]
    temporal = result["temporal_drift_1x2"]["h2h"]["windows"]
    assert temporal
    assert all(window["calibration_bias"]["scope"] == "development_only" for window in temporal)
    assert all(
        window["date_end"] < result["split"]["holdout_start"][:10]
        for window in temporal
    )
    assert all(
        set(window["calibration_bias"]["outcomes"]) == {"home", "draw", "away"}
        for window in temporal
    )


def test_1x2_bias_segments_explain_associations_without_claiming_causality():
    from football_research_validation import _calibration_bias_segments

    rows = []
    for index in range(240):
        row = _row(index, f"S{index // 60 + 1}", ("home", "draw", "away")[index % 3])
        confidence_band = (index // 3) % 3
        row["base"] = (
            {"home": 0.40, "draw": 0.35, "away": 0.25}
            if confidence_band == 0 else
            {"home": 0.50, "draw": 0.30, "away": 0.20}
            if confidence_band == 1 else
            {"home": 0.70, "draw": 0.20, "away": 0.10}
        )
        row["candidate"] = dict(row["base"])
        row["h2h_valid_meetings"] = (0, 2, 6, 12)[(index // 3) % 4]
        row["h2h_adjusted"] = index % 2 == 0
        rows.append(row)

    result = _calibration_bias_segments(
        rows, "candidate", 42,
        ("base_confidence", "h2h_sample", "h2h_adjustment", "probability_shift"),
    )
    assert set(result) == {
        "base_confidence", "h2h_sample", "h2h_adjustment", "probability_shift"
    }
    assert sum(item["sample_size"] for item in result["base_confidence"]["segments"]) == 240
    assert len(result["base_confidence"]["segments"]) == 3
    assert len(result["h2h_sample"]["segments"]) == 4
    assert len(result["h2h_adjustment"]["segments"]) == 2
    assert all(item["eligible_for_descriptive_comparison"] for group in result.values() for item in group["segments"])
    assert all(item["bias"]["scope"] == "development_only" for group in result.values() for item in group["segments"])


def test_1x2_bias_segments_use_development_only_and_mark_small_groups():
    rows = []
    for index in range(700):
        row = _row(index, f"S{index // 175 + 1}", ("home", "draw", "away")[index % 3])
        row["h2h_valid_meetings"] = 0 if index % 7 else 12
        row["h2h_adjusted"] = index % 2 == 0
        rows.append(row)

    result = build_candidate_validation({"per_match": rows})
    segments = result["calibration_bias_1x2"]["segments"]["h2h"]
    assert result["split"]["development_matches"] == 560
    assert result["split"]["holdout_matches"] == 140
    for dimension in segments.values():
        assert sum(item["sample_size"] for item in dimension["segments"]) == 560
        assert all(
            item["bias"]["scope"] == "development_only"
            for item in dimension["segments"]
        )
        assert all(
            result["split"]["holdout_start"][:10] > max(
                row["kickoff_at"][:10]
                for row in rows[:560]
            )
            for item in dimension["segments"]
        )
    small = _calibration_bias_segments(
        rows[:20], "candidate", 5, ("h2h_sample",)
    )["h2h_sample"]["segments"]
    assert small
    assert all(not item["eligible_for_descriptive_comparison"] for item in small)
