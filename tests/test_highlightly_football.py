from highlightly_football_client import normalize_name
from football_highlightly_shadow import MODEL_VERSION, predict_highlightly_shadow


def fixture():
    return {"homeTeam":{"id":1,"name":"Alpha"},"awayTeam":{"id":2,"name":"Beta"},
            "league":{"id":99,"name":"Test League","season":2026}}


def stats(team, home=None, away=None):
    return [{"leagueId":99,"season":2026,
             "home":{"games":{"played":10},"goals":{"scored":20,"received":8}},
             "away":{"games":{"played":10},"goals":{"scored":12,"received":15}},
             "total":{"games":{"played":20},"goals":{"scored":32,"received":23}}}]


def recent(team_id, for_goals=2, against=1):
    rows=[]
    for i in range(5):
        rows.append({"date":f"2026-10-{20-i:02d}T15:00:00Z",
                     "homeTeam":{"id":team_id,"name":"Team"},"awayTeam":{"id":9,"name":"Opponent"},
                     "state":{"description":"Finished","score":{"current":f"{for_goals} - {against}"}}})
    return rows


def test_team_name_normalization_handles_accents_and_punctuation():
    assert normalize_name("Atlético-Madrid") == "atletico madrid"


def test_highlightly_shadow_returns_markets_and_stays_experimental():
    result=predict_highlightly_shadow(fixture(),recent(1),recent(2),stats(1),stats(2),[],
                                      "2026-11-04T20:00:00Z")
    assert result["available"] is True
    assert result["model_version"] == MODEL_VERSION
    assert abs(sum(result["probabilities"].values())-1) < 1e-5
    assert result["recommendation"]["status"] == "NO_PLAY_UNTIL_VALIDATED"


def test_missing_team_statistics_does_not_fabricate_prediction():
    result=predict_highlightly_shadow(fixture(),recent(1),recent(2),[],stats(2),[],
                                      "2026-11-04T20:00:00Z")
    assert result["available"] is False
