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
        "kickoff_at": f"{date(2000, 1, 1) + timedelta(days=index)}T00:00:00+00:00",
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
    assert result["protocol"] == "chronological_holdout_paired_bootstrap_v1"
    assert result["split"]["development_matches"] == 400
    assert result["split"]["holdout_matches"] == 100
    assert result["split"]["holdout_start"] == rows[400]["kickoff_at"]
    assert len(result["season_breakdown"]) == 4
    h2h = result["candidates"]["h2h"]
    assert h2h["holdout"]["sample_size"] == 100
    assert h2h["holdout"]["brier_delta"]["ci_95"][1] < 0
    assert h2h["holdout"]["log_loss_delta"]["ci_95"][1] < 0
    assert h2h["gate"]["status"] == "APTO_PARA_REVISION"
    assert h2h["gate"]["automatic_activation"] is False


def test_validation_refuses_small_holdout_and_missing_seasons():
    rows = [_row(index, "S1") for index in range(30)]
    result = build_candidate_validation({"per_match": rows})
    gate = result["candidates"]["h2h"]["gate"]
    assert result["split"]["holdout_matches"] == 6
    assert gate["status"] == "MUESTRA_INSUFICIENTE"
    assert gate["automatic_activation"] is False
    assert gate["reasons"]


def test_validation_bootstrap_is_deterministic():
    rows = [_row(index, f"S{index // 100}") for index in range(500)]
    first = build_candidate_validation({"per_match": rows})
    second = build_candidate_validation({"per_match": rows})
    assert first["candidates"]["h2h"]["holdout"]["brier_delta"] == second["candidates"]["h2h"]["holdout"]["brier_delta"]
