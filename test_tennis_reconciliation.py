from datetime import date

import pytest

import tennis_reconciliation as reconciliation


def external_row(day, *, league="ATP", category="Main tour", p1="Player One", p2="Player Two", winner="1", tournament="Example Open", match_id="external-1"):
    return {
        "date": f"{day}T14:30:00+00:00",
        "genre": league,
        "categorie": category,
        "joueur1": p1,
        "joueur2": p2,
        "joueur1_id": "1",
        "joueur2_id": "2",
        "vainqueur_id": winner,
        "tournoi": tournament,
        "match_id": match_id,
    }


def sackmann_row(day, *, winner="Player One", loser="Player Two", tournament="Example Open", score="6-4 6-3"):
    return {
        "tourney_date": day.replace("-", ""),
        "winner_name": winner,
        "loser_name": loser,
        "tourney_name": tournament,
        "score": score,
        "surface": "Hard",
    }


def test_reconciliation_reports_unique_candidate_without_merging(monkeypatch):
    ext = (external_row("2026-06-10"), external_row("2026-06-11", category="ITF", match_id="excluded"))
    sack = (sackmann_row("2026-06-08"),)
    monkeypatch.setattr(reconciliation, "load_external_year", lambda year: ext if year == 2026 else ())
    monkeypatch.setattr(reconciliation, "load_year", lambda league, year: sack if year == 2026 else ())

    result = reconciliation.audit_external_reconciliation("ATP", "2026-06-01", "2026-06-30")

    assert result["status"] == "source_reconciliation_audit_only"
    assert result["model_status"] == "research_only"
    assert result["counts"]["eligible_external_matches"] == 1
    assert result["counts"]["unique_candidates"] == 1
    assert result["counts"]["no_candidate"] == 0
    assert result["counts"]["excluded_categories"] == {"ITF": 1}
    assert result["matching_policy"]["automatic_merge"] is False


def test_reconciliation_keeps_ambiguous_candidates_for_review(monkeypatch):
    ext = (external_row("2026-06-10"),)
    sack = (
        sackmann_row("2026-06-08"),
        sackmann_row("2026-06-09", score="7-5 6-4"),
    )
    monkeypatch.setattr(reconciliation, "load_external_year", lambda year: ext if year == 2026 else ())
    monkeypatch.setattr(reconciliation, "load_year", lambda league, year: sack if year == 2026 else ())

    result = reconciliation.audit_external_reconciliation("ATP", "2026-06-01", "2026-06-30")

    assert result["counts"]["ambiguous_candidates"] == 1
    assert result["review_samples"][0]["candidate_count"] == 2


def test_reconciliation_validates_league_window_and_dates(monkeypatch):
    monkeypatch.setattr(reconciliation, "load_external_year", lambda year: ())
    monkeypatch.setattr(reconciliation, "load_year", lambda league, year: ())
    with pytest.raises(ValueError, match="ATP o WTA"):
        reconciliation.audit_external_reconciliation("ITF", "2026-06-01", "2026-06-30")
    with pytest.raises(ValueError, match="122 días"):
        reconciliation.audit_external_reconciliation("ATP", "2026-01-01", "2026-05-03")
    with pytest.raises(ValueError, match="posterior"):
        reconciliation.audit_external_reconciliation("WTA", "2026-06-30", "2026-06-01")


def test_reconciliation_rejects_invalid_external_winner(monkeypatch):
    ext = (external_row("2026-06-10", winner="99"),)
    monkeypatch.setattr(reconciliation, "load_external_year", lambda year: ext if year == 2026 else ())
    monkeypatch.setattr(reconciliation, "load_year", lambda league, year: ())
    result = reconciliation.audit_external_reconciliation("ATP", "2026-06-01", "2026-06-30")
    assert result["counts"]["eligible_external_matches"] == 0
    assert result["counts"]["invalid_external_results_in_eligible_window"] == 1
