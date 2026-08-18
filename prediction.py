from math import exp
def baseline_prediction():
    p=1/(1+exp(-0.15))
    return {"home_probability":round(p,6),"away_probability":round(1-p,6),
    "confidence":"Inicial","data_quality":72,
    "features":{"note":"Baseline experimental; historical features not yet connected."}}
