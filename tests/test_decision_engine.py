from decision_engine import evaluate_decision


def test_expected_value_and_fair_odds():
    result = evaluate_decision(
        sport="MLB",
        model_probability=0.60,
        decimal_odds=1.80,
        data_quality=90,
    )
    assert result["classification"] == "VALUE_CANDIDATE"
    assert result["fair_odds"] == 1.6667
    assert result["expected_value_percent"] == 8.0
    assert result["is_guaranteed"] is False


def test_missing_data_blocks_value_label():
    result = evaluate_decision(
        sport="NBA",
        model_probability=0.65,
        decimal_odds=1.80,
        data_quality=40,
    )
    assert result["classification"] == "NO_PLAY"


def test_risk_signals_flag_high_risk():
    result = evaluate_decision(
        sport="MLB",
        model_probability=0.60,
        decimal_odds=1.90,
        data_quality=80,
        risk_signals=["Abridor no confirmado"],
    )
    assert result["classification"] == "HIGH_RISK"


def test_upset_requires_market_comparison_and_clean_data():
    result = evaluate_decision(
        sport="NFL",
        model_probability=0.48,
        decimal_odds=2.20,
        market_probability=0.40,
        data_quality=90,
    )
    assert result["classification"] == "UPSET_CANDIDATE"
    assert result["model_market_gap_percentage_points"] == 8.0


def test_invalid_odds_rejected():
    try:
        evaluate_decision(
            sport="TENNIS",
            model_probability=0.55,
            decimal_odds=1.0,
        )
    except ValueError as exc:
        assert "decimal_odds" in str(exc)
    else:
        raise AssertionError("Expected invalid odds to raise ValueError")



def test_two_odds_estimate_no_vig_market_probability():
    result = evaluate_decision(
        sport="MLB",
        model_probability=0.55,
        decimal_odds=1.90,
        opponent_decimal_odds=2.10,
        data_quality=90,
    )
    assert result["calculated_no_vig_market_probability"] is not None
    assert result["market_overround_percentage"] > 0
    assert "normalizando" in " ".join(result["warnings"])


def test_opponent_probability_pair_consistency_warning():
    result = evaluate_decision(
        sport="NBA",
        model_probability=0.60,
        decimal_odds=1.80,
        opponent_model_probability=0.35,
        data_quality=90,
    )
    assert result["model_probabilities_consistent"] is False
    assert any("no suman" in warning for warning in result["warnings"])


def test_complementary_probabilities_are_consistent():
    result = evaluate_decision(
        sport="TENNIS",
        model_probability=0.554,
        decimal_odds=2.15,
        opponent_model_probability=0.446,
        opponent_decimal_odds=1.80,
        data_quality=90,
    )
    assert result["model_probabilities_consistent"] is True
