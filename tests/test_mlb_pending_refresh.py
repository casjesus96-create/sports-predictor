from repository import _pending_refresh_reason


def _snapshot(*, quality=70, home_probability=0.51, away_probability=0.49, factors=None):
    return {
        "data_quality": quality,
        "home_probability": home_probability,
        "away_probability": away_probability,
        "features": {
            "predicted_winner": "Home",
            "factors": factors or {},
        },
    }


def _analysis(*, quality=70, home_probability=0.51, away_probability=0.49, factors=None):
    return {
        "data_quality": quality,
        "home_probability": home_probability,
        "away_probability": away_probability,
        "features": {
            "predicted_winner": "Home",
            "factors": factors or {},
        },
    }


def _matchups(home_confirmed=False, away_confirmed=False, home_ids=None, away_ids=None,
              home_available=0, away_available=0):
    def team(confirmed, ids, available):
        hitters = []
        for index, player_id in enumerate(ids or [], start=1):
            hitters.append({
                "player_id": player_id,
                "player_name": f"Player {player_id}",
                "vs_pitcher": {"available": index <= available},
            })
        return {
            "lineup_confirmed": confirmed,
            "lineup_status": "confirmed" if confirmed else "not_found",
            "hitters": hitters,
        }

    return {
        "batter_pitcher_matchups": {
            "home_team": team(home_confirmed, home_ids, home_available),
            "away_team": team(away_confirmed, away_ids, away_available),
        }
    }


def test_no_material_change_preserves_pending_snapshot():
    existing = _snapshot(factors=_matchups())
    fresh = _analysis(factors=_matchups())
    assert _pending_refresh_reason(existing, fresh) is None


def test_new_confirmed_lineup_triggers_refresh():
    existing = _snapshot(factors=_matchups())
    fresh = _analysis(factors=_matchups(home_confirmed=True, home_ids=[11, 12, 13]))
    assert "alineaciones confirmadas" in _pending_refresh_reason(existing, fresh).lower()


def test_more_batter_pitcher_history_triggers_refresh():
    previous = _matchups(home_confirmed=True, home_ids=[11, 12], home_available=0)
    improved = _matchups(home_confirmed=True, home_ids=[11, 12], home_available=2)
    reason = _pending_refresh_reason(_snapshot(factors=previous), _analysis(factors=improved))
    assert "historial directo" in reason.lower()


def test_probability_difference_alone_does_not_refresh_without_evidence():
    existing = _snapshot(home_probability=0.51, away_probability=0.49)
    fresh = _analysis(home_probability=0.54, away_probability=0.46)
    assert _pending_refresh_reason(existing, fresh) is None


def test_material_data_quality_gain_triggers_refresh():
    existing = _snapshot(quality=70)
    fresh = _analysis(quality=75)
    assert "cobertura de datos" in _pending_refresh_reason(existing, fresh).lower()
