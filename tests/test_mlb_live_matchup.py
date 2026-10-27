from mlb_live_matchup import build_live_pitcher_matchup_stats


def test_live_matchup_counts_hits_and_at_bats_by_pitcher():
    plays = [
        {"matchup": {"batter": {"id": 10}, "pitcher": {"id": 20, "fullName": "Freddy Peralta"}}, "result": {"eventType": "single", "isAtBat": True}},
        {"matchup": {"batter": {"id": 10}, "pitcher": {"id": 20, "fullName": "Freddy Peralta"}}, "result": {"eventType": "double", "isAtBat": True}},
        {"matchup": {"batter": {"id": 10}, "pitcher": {"id": 20, "fullName": "Freddy Peralta"}}, "result": {"eventType": "walk", "isAtBat": False}},
        {"matchup": {"batter": {"id": 10}, "pitcher": {"id": 30, "fullName": "Reliever"}}, "result": {"eventType": "strikeout", "isAtBat": True}},
    ]
    stats = build_live_pitcher_matchup_stats(plays)[10]
    peralta = next(row for row in stats if row["pitcher_id"] == 20)
    reliever = next(row for row in stats if row["pitcher_id"] == 30)
    assert (peralta["hits"], peralta["at_bats"], peralta["avg"]) == (2, 2, 1.0)
    assert (reliever["hits"], reliever["at_bats"], reliever["avg"]) == (0, 1, 0.0)


def test_live_matchup_ignores_incomplete_plays_and_invalid_ids():
    assert build_live_pitcher_matchup_stats([
        {"matchup": {"batter": {"id": 10}, "pitcher": {"id": 20}}, "result": {}},
        {"matchup": {"batter": {}, "pitcher": {"id": 20}}, "result": {"eventType": "single"}},
    ]) == {}
