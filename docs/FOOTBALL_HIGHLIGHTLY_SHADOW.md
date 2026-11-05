# Highlightly Football shadow integration

- Direct Highlightly host: `https://soccer.highlightly.net`.
- Secret: `HIGHLIGHTLY_API_KEY` in the backend environment only.
- Authentication header: `x-rapidapi-key`; no `x-rapidapi-host` for direct Highlightly.
- The client caches requests by endpoint and parameters to protect the free quota.
- Fixture linking is strict: same UTC calendar date and normalized exact home/away team names; zero or multiple matches are rejected.
- The experimental model uses season home/away goals for/against and the last five completed games. H2H is displayed as a feature count but does not currently change probabilities.
- Match statistics are fetched only for an identified Highlightly match ID and are display-only; they are never passed into pre-match predictions.
- The official football model and its snapshots are not modified.
- Experimental output is marked not calibrated / NO_PLAY_UNTIL_VALIDATED.


## Independent Highlightly competition catalog

- `GET /api/v1/football/highlightly/competitions` returns the paginated Highlightly league catalog, preserving each league's provider-native ID, name, country and season metadata.
- `GET /api/v1/football/highlightly/games?leagueId={id}&date=YYYY-MM-DD` lists fixtures scoped to the selected Highlightly league ID and date. Team names are displayed as Highlightly returns them; no cross-provider name matching is performed.
- `GET /api/v1/football/highlightly/matches/{id}/analysis` retrieves a match by its Highlightly ID and builds a read-only experimental analysis using Highlightly team IDs.
- The Football Predictor UI exposes a separate Highlightly catalog explorer. Its output is not written to official prediction snapshots, official history, or official model calibration.
- Catalog requests use a long process-local cache; fixture requests use the existing short cache. Catalog pagination is bounded to protect the subscription quota.
- The number of leagues shown is the number returned by the configured Highlightly subscription; plan-level coverage restrictions still apply.
