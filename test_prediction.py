from prediction import baseline_prediction
def test_probability_sum():
 r=baseline_prediction()
 assert round(r["home_probability"]+r["away_probability"],6)==1
