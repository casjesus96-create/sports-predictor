# Advanced football goals candidate

This is a shadow-only candidate; official `FOOTBALL-POISSON-0.5.0` and official
snapshots remain unchanged.

- Strict pre-kickoff filter: only FINISHED/AWARDED fixtures with valid timezone-aware
  timestamps earlier than target kickoff.
- Recency weight: `exp(-ln(2) * age_days / 120)`.
- Team form: latest 10 matches, venue-specific latest 8 weighted 70%, all-venue
  recent form 30%; rates shrink toward league scoring baselines with a 6-match prior.
- Opponent defence: modest adjustment using weighted goals-conceded rate, capped
  to 0.80–1.20.
- H2H: last 6 direct meetings; maximum blend 18%, regularized by 10 prior meetings.
- One normalized independent-Poisson score matrix derives 1X2, expected goals,
  BTTS, totals and likely scorelines.

No 90% claim, betting recommendation or official activation until a sufficient
walk-forward sample demonstrates improved Brier, Log Loss and calibration by
competition. API-Football post-match stats are not pre-match inputs.
