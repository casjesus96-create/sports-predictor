from decision_api import _snapshot_summary, _sport_from_row


def test_snapshot_summary_uses_saved_official_probabilities():
    row = {
        "id": "8b6cb6a7-b8c3-4e93-8ab1-8b8a55c0f911",
        "event_id": "849816",
        "sport": "baseball",
        "league": "MLB",
        "model_version": "2.0.0-matchup",
        "created_at": "2026-10-18T10:00:00+00:00",
        "result_status": "PENDING",
        "home_probability": 0.44,
        "away_probability": 0.56,
        "data_quality": 90,
        "features": {
            "game": {
                "home": "Home Club",
                "away": "Away Club",
            }
        },
    }

    result = _snapshot_summary(row)

    assert result is not None
    assert result["sport"] == "MLB"
    assert result["home_probability"] == 0.44
    assert result["away_probability"] == 0.56
    assert result["home"] == "Home Club"
    assert result["away"] == "Away Club"


def test_snapshot_summary_rejects_missing_probabilities():
    row = {
        "id": "snapshot-id",
        "sport": "NBA",
        "league": "NBA",
        "home_probability": None,
        "away_probability": 0.52,
        "features": {},
    }
    assert _snapshot_summary(row) is None


def test_sport_aliases_are_normalized():
    assert _sport_from_row({"sport": "baseball"}) == "MLB"
    assert _sport_from_row({"league": "NFL", "sport": "football"}) == "NFL"
    assert _sport_from_row({"league": "NBA"}) == "NBA"
