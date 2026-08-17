from budget_profiles import normalize_token_budget_profile, token_budget_for


def test_quality_profile_is_available_with_larger_council_limits():
    quality = token_budget_for("quality")

    assert normalize_token_budget_profile("QUALITY") == "quality"
    assert quality["phase1"] > token_budget_for("performance")["phase1"]
    assert quality["phase3"] > token_budget_for("performance")["phase3"]
