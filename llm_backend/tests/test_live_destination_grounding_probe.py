from scripts.live_destination_grounding_probe import (
    _health_status,
    apply_targeted_criteria,
    configured_provider_capabilities,
)


def test_configured_provider_capabilities_never_exposes_keys():
    capabilities = configured_provider_capabilities()

    assert set(capabilities) == {"amap", "geoapify", "serpapi"}
    for state in capabilities.values():
        assert set(state) == {"key_configured", "enabled", "live_enabled", "cache_enabled"}
        assert all(isinstance(value, bool) for value in state.values())


def test_health_status_separates_safe_readiness_from_provider_or_media_degradation():
    assert _health_status(status="ready", provider_degraded=False, quality_flags=[]) == "healthy"
    assert _health_status(status="ready", provider_degraded=True, quality_flags=[]) == "degraded"
    assert _health_status(status="ready", provider_degraded=False, quality_flags=["low_image_coverage"]) == "degraded"
    assert _health_status(status="insufficient_candidates", provider_degraded=False, quality_flags=[]) == "not_ready"


def test_targeted_probe_uses_selected_case_expectations_instead_of_global_thresholds():
    report = {
        "status": "failed",
        "criteria": {"min_resolved_profiles": 6, "min_ready_destinations": 4},
        "results": [
            {"case_id": "unseen_dunhuang", "status": "ready"},
            {"case_id": "unseen_kashgar_insufficient", "status": "insufficient_candidates"},
        ],
    }
    cases = [
        {"case_id": "unseen_dunhuang", "expected_outcome": "ready"},
        {"case_id": "unseen_kashgar_insufficient", "expected_outcome": "insufficient_candidates"},
    ]

    result = apply_targeted_criteria(report, cases)

    assert result["status"] == "passed"
    assert result["criteria"]["mode"] == "targeted"
    assert result["mismatches"] == []


def test_targeted_probe_reports_outcome_mismatch():
    report = {
        "status": "passed",
        "results": [{"case_id": "unseen_dunhuang", "status": "insufficient_candidates"}],
    }
    result = apply_targeted_criteria(
        report,
        [{"case_id": "unseen_dunhuang", "expected_outcome": "ready"}],
    )

    assert result["status"] == "failed"
    assert result["mismatches"] == [
        {"case_id": "unseen_dunhuang", "expected": "ready", "actual": "insufficient_candidates"}
    ]
