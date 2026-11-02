from football_promotion_gate import promotion_gate


def metrics(n=300, brier=0.52, log_loss=1.05):
    return {"sample_size": n, "brier_score": brier, "log_loss": log_loss}


def test_candidate_requires_both_scoring_rules_to_improve():
    result = promotion_gate(metrics(), metrics(brier=0.51, log_loss=1.04))
    assert result["status"] == "ELIGIBLE_FOR_REVIEW"
    assert result["eligible_for_review"] is True
    assert result["automatic_activation"] is False
    assert result["official_model_unchanged"] is True


def test_small_sample_is_not_eligible():
    result = promotion_gate(metrics(n=249), metrics(n=249, brier=0.1, log_loss=0.2))
    assert result["status"] == "INSUFFICIENT_SAMPLE"
    assert result["eligible_for_review"] is False


def test_unpaired_samples_are_rejected():
    result = promotion_gate(metrics(n=300), metrics(n=299, brier=0.4, log_loss=0.8))
    assert result["status"] == "UNPAIRED_SAMPLE"
    assert result["eligible_for_review"] is False


def test_improvement_in_only_one_metric_does_not_pass():
    result = promotion_gate(metrics(), metrics(brier=0.50, log_loss=1.06))
    assert result["status"] == "NO_PROMOTION"
    assert result["eligible_for_review"] is False


def test_invalid_metrics_are_rejected():
    result = promotion_gate({"sample_size": 300}, metrics())
    assert result["status"] == "INSUFFICIENT_METRICS"
    assert result["eligible_for_review"] is False
