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
