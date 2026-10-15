"""Read-only reconciliation audit between Valuebetennis and Sackmann tennis history.

This module produces candidate links for human review only. It never merges,
rewrites, or trains on external records. Candidate matches require the same
normalized player pair and tournament name, with the Sackmann tournament start
date within 21 days of the external UTC match date.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from tennis_external_source import (
    ExternalTennisSourceError,
    _match_day,
    _parse_date,
    load_external_year,
)
from tennis_history import HistoricalDataError, _match_date, load_year, normalize_player_name

SUPPORTED_LEAGUES = {"ATP", "WTA"}
MAX_RECONCILIATION_DAYS = 122
MAX_SAMPLE_CANDIDATES = 20
DATE_TOLERANCE_DAYS = 21
ELIGIBLE_CATEGORIES = {"main tour", "masters", "grand chelem", "grand slam"}


def _normalized(value: Any) -> str:
    return normalize_player_name(str(value or ""))


def _external_valid_result(row: dict[str, str]) -> bool:
    player1_id = str(row.get("joueur1_id") or "").strip()
    player2_id = str(row.get("joueur2_id") or "").strip()
    winner_id = str(row.get("vainqueur_id") or "").strip()
    return bool(player1_id and player2_id and player1_id != player2_id and winner_id in {player1_id, player2_id})


def _historical_valid(row: dict[str, str]) -> bool:
    winner = str(row.get("winner_name") or "").strip()
    loser = str(row.get("loser_name") or "").strip()
    score = str(row.get("score") or "").casefold().strip()
    return bool(
        winner
        and loser
        and _normalized(winner) != _normalized(loser)
        and "walkover" not in score
        and "w/o" not in score
        and score not in {"wo", "def"}
    )


def audit_external_reconciliation(
    league: str,
    start_date: str | date,
    end_date: str | date,
) -> dict[str, Any]:
    """Return conservative source-to-source candidate counts, without merging rows."""
    selected_league = str(league or "").strip().upper()
    if selected_league not in SUPPORTED_LEAGUES:
        raise ValueError("league debe ser ATP o WTA.")
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if end < start:
        raise ValueError("end_date debe ser igual o posterior a start_date.")
    if (end - start).days + 1 > MAX_RECONCILIATION_DAYS:
        raise ValueError("El periodo de conciliación no puede superar 122 días.")
    if start.year < 2021:
        raise ValueError("La fuente externa de conciliación comienza en 2021.")

    # Expand historical tournament-start dates around the requested external
    # match-date window; these are not semantically identical date fields.
    candidate_start = start - timedelta(days=DATE_TOLERANCE_DAYS)
    candidate_end = end + timedelta(days=DATE_TOLERANCE_DAYS)
    historical_rows: list[tuple[date, dict[str, str]]] = []
    historical_rows_seen = 0
    for year in range(candidate_start.year, candidate_end.year + 1):
        for row in load_year(selected_league, year):
            historical_rows_seen += 1
            played_on = _match_date(row)
            if played_on and candidate_start <= played_on <= candidate_end and _historical_valid(row):
                historical_rows.append((played_on, row))

    # Index by unordered normalized player pair and normalized tournament.
    historical_index: dict[tuple[tuple[str, str], str], list[tuple[date, dict[str, str]]]] = defaultdict(list)
    for played_on, row in historical_rows:
        players = tuple(sorted((_normalized(row.get("winner_name")), _normalized(row.get("loser_name")))))
        tournament = _normalized(row.get("tourney_name"))
        if players[0] and players[1] and tournament:
            historical_index[(players, tournament)].append((played_on, row))

    category_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    excluded_categories: Counter[str] = Counter()
    external_seen = 0
    external_rows_in_window = 0
    eligible_external_matches = 0
    invalid_external_results = 0
    invalid_external_dates = 0
    external_match_ids: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []

    for year in range(start.year, end.year + 1):
        for row in load_external_year(year):
            external_seen += 1
            if str(row.get("genre") or "").strip().upper() != selected_league:
                continue
            match_day = _match_day(row.get("date", ""))
            if match_day is None:
                invalid_external_dates += 1
                continue
            if not start <= match_day <= end:
                continue
            external_rows_in_window += 1
            match_id = str(row.get("match_id") or "").strip()
            if match_id:
                external_match_ids[match_id] += 1

            category_raw = str(row.get("categorie") or "").strip() or "unknown"
            category_key = _normalized(category_raw)
            if category_key not in ELIGIBLE_CATEGORIES:
                excluded_categories[category_raw] += 1
                continue
            category_counts[category_raw] += 1
            if not _external_valid_result(row):
                invalid_external_results += 1
                continue

            player1 = _normalized(row.get("joueur1"))
            player2 = _normalized(row.get("joueur2"))
            tournament = _normalized(row.get("tournoi"))
            if not player1 or not player2 or player1 == player2 or not tournament:
                invalid_external_results += 1
                continue

            eligible_external_matches += 1
            players = tuple(sorted((player1, player2)))
            possible = historical_index.get((players, tournament), [])
            candidates = [
                (candidate_day, candidate)
                for candidate_day, candidate in possible
                if abs((candidate_day - match_day).days) <= DATE_TOLERANCE_DAYS
            ]
            if len(candidates) == 1:
                outcome = "unique_candidate"
            elif len(candidates) > 1:
                outcome = "ambiguous_candidates"
            else:
                outcome = "no_candidate"
            outcome_counts[outcome] += 1

            if len(samples) < MAX_SAMPLE_CANDIDATES and outcome != "unique_candidate":
                samples.append({
                    "external_match_id": match_id or None,
                    "external_date_utc": match_day.isoformat(),
                    "category": category_raw,
                    "tournament": str(row.get("tournoi") or ""),
                    "player1": str(row.get("joueur1") or ""),
                    "player2": str(row.get("joueur2") or ""),
                    "candidate_count": len(candidates),
                    "reconciliation_status": outcome,
                    "candidate_sackmann_matches": [
                        {
                            "tournament_date": candidate_day.isoformat(),
                            "tournament": str(candidate.get("tourney_name") or ""),
                            "winner": str(candidate.get("winner_name") or ""),
                            "loser": str(candidate.get("loser_name") or ""),
                            "score": str(candidate.get("score") or ""),
                            "date_gap_days": abs((candidate_day - match_day).days),
                        }
                        for candidate_day, candidate in candidates[:3]
                    ],
                })

    duplicate_external_rows = sum(count - 1 for count in external_match_ids.values() if count > 1)
    return {
        "success": True,
        "status": "source_reconciliation_audit_only",
        "model_status": "research_only",
        "league": selected_league,
        "requested_window": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "matching_policy": {
            "external_date_semantics": "exact match date/time converted to UTC date",
            "historical_date_semantics": "tournament start date",
            "eligible_external_categories": sorted(ELIGIBLE_CATEGORIES),
            "excluded_categories": "All other categories, including Challenger, ITF, team events, and unknown",
            "player_match": "unordered pair of normalized player names",
            "tournament_match": "exact normalized tournament name",
            "maximum_date_gap_days": DATE_TOLERANCE_DAYS,
            "automatic_merge": False,
        },
        "counts": {
            "external_rows_seen_across_loaded_year_files": external_seen,
            "external_rows_in_requested_window": external_rows_in_window,
            "eligible_external_matches": eligible_external_matches,
            "eligible_categories": dict(sorted(category_counts.items())),
            "excluded_categories": dict(sorted(excluded_categories.items())),
            "invalid_external_dates_in_loaded_league_rows": invalid_external_dates,
            "invalid_external_results_in_eligible_window": invalid_external_results,
            "sackmann_rows_seen_across_loaded_year_files": historical_rows_seen,
            "sackmann_valid_matches_in_expanded_candidate_window": len(historical_rows),
            "unique_candidates": outcome_counts.get("unique_candidate", 0),
            "ambiguous_candidates": outcome_counts.get("ambiguous_candidates", 0),
            "no_candidate": outcome_counts.get("no_candidate", 0),
            "duplicate_external_match_id_rows": duplicate_external_rows,
            "sample_limit": MAX_SAMPLE_CANDIDATES,
        },
        "review_samples": samples,
        "limitations": [
            "Audit only: no external records are merged, deduplicated, or used for training.",
            "A unique candidate is a review lead, not proof that two records represent the same match.",
            "Tournament-name aliases and player-name variants can cause false negatives.",
            "The 21-day tolerance accounts for tournament-start dates but can produce ambiguous candidates.",
            "Category labels must be verified against the intended competition scope.",
            "Valuebetennis CC BY 4.0 attribution is required for any reuse.",
            "The existing Sackmann archive has CC BY-NC-SA 4.0 terms; commercial compatibility requires separate review.",
        ],
    }
