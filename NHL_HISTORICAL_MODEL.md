# NHL historical Elo research model

## Scope
The NHL Elo engine is a pure, research-only calculation over already-approved Sports Predictor archive rows. It does not call an NHL endpoint, query Supabase, persist data, or change the active model status in the NHL UI.

## First market
The first supported market is game winner including overtime/shootout (moneyline): home win versus away win. Regulation-time 1X2 and totals remain out of scope until the archive contains sufficient, consistently defined outcomes.

## Data and leakage controls
Only rows marked training_eligible=true and result_status=FINAL, with canonical team identities, integer non-tied scores, and the selected game type are eligible. Game type 2 (regular season) and 3 (playoffs) are modeled separately. Games on or after the requested cutoff date are excluded. Duplicate game IDs are deduplicated; contradictory duplicates fail closed.

Ratings are replayed chronologically using home-ice advantage and a bounded score-margin multiplier. The output reports total and per-team sample counts. Odds, external team statistics, live boxscores, and current NHL feed data are not inputs.

## Probability gate
Defaults require at least 30 eligible historical games overall and at least 5 games per participating team. These are conservative activation gates, not claims of calibration. If the gate is not met, status is INSUFFICIENT_HISTORICAL_SAMPLE and probabilities is null; the system must not display a fabricated percentage.

## Promotion requirements
This model remains research-only. Official promotion requires a rights-reviewed populated archive, chronological walk-forward backtesting, Brier score/log loss, calibration analysis, season/team coverage checks, and comparison against a simple baseline. This module does not authorize model promotion.
