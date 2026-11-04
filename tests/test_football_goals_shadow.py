from football_goals_shadow import MODEL_VERSION, predict_advanced_shadow


def fixture(i, home, away, hg, ag, day):
    return {"id":i,"status":"FINISHED","utcDate":f"2026-01-{day:02d}T15:00:00Z",
            "homeTeam":{"name":home},"awayTeam":{"name":away},
            "score":{"fullTime":{"home":hg,"away":ag}}}


def sample():
    scores=[(2,0),(1,1),(0,1),(3,1),(1,0),(2,2),(0,2),(2,1),
            (1,0),(2,1),(1,2),(2,0),(1,1),(3,0),(0,1),(2,2)]
    return [fixture(i,"Alpha" if i%2 else "Beta","Beta" if i%2 else "Alpha",*score,i)
            for i,score in enumerate(scores,1)]


def test_shadow_markets_are_consistent_and_explicitly_unvalidated():
    result=predict_advanced_shadow("Alpha","Beta",sample(),"2026-02-01T15:00:00Z")
    assert result["available"] is True
    assert result["model_version"]==MODEL_VERSION
    assert abs(sum(result["probabilities"].values())-1)<1e-5
    btts=result["goal_markets"]["both_teams_to_score"]
    assert abs(btts["yes"]+btts["no"]-1)<1e-5
    assert result["recommendation"]["status"]=="NO_PLAY_UNTIL_VALIDATED"


def test_future_matches_are_excluded():
    rows=sample()+[fixture(99,"Alpha","Beta",8,0,28)]
    result=predict_advanced_shadow("Alpha","Beta",rows,"2026-01-25T15:00:00Z")
    assert result["available"] is True
    assert result["sample"]["excluded_at_or_after_kickoff"]==1


def test_h2h_is_low_weight_and_reported():
    result=predict_advanced_shadow("Alpha","Beta",sample(),"2026-02-01T15:00:00Z")
    assert result["h2h"]["sample_size"]>0
    assert 0<result["h2h"]["weight_applied"]<=0.18
