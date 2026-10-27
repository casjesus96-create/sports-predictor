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



def test_resolve_active_batting_side_prefers_mlb_offense_team_id():
    from mlb_live_matchup import resolve_active_batting_side

    linescore = {
        "inningState": "Middle",
        "offense": {"team": {"id": 108}},
    }
    game_teams = {"away": {"id": 109}, "home": {"id": 108}}
    assert resolve_active_batting_side(linescore, game_teams) == "home"


def test_resolve_active_batting_side_only_falls_back_for_explicit_halves():
    from mlb_live_matchup import resolve_active_batting_side

    game_teams = {"away": {"id": 109}, "home": {"id": 108}}
    assert resolve_active_batting_side({"inningState": "Top"}, game_teams) == "away"
    assert resolve_active_batting_side({"inningState": "Bottom"}, game_teams) == "home"
    assert resolve_active_batting_side({"inningState": "Middle"}, game_teams) is None
    assert resolve_active_batting_side({}, game_teams) is None
