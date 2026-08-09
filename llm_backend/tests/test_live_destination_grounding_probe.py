from scripts.live_destination_grounding_probe import (
    DEFAULT_CASE_IDS,
    _health_status,
    apply_targeted_criteria,
    configured_provider_capabilities,
    evaluate_live_acceptance,
    summarize_probe_results,
)


def _result(
    case_id: str,
    *,
    status: str = "ready",
    resolved: bool = True,
    validated: int = 3,
    provider: int = 4,
    evidence: int = 3,
    images: int = 3,
    cross_city_published: int = 0,
    mock_published: int = 0,
    elapsed_ms: float = 1200,
) -> dict:
    return {
        "case_id": case_id,
        "status": status,
        "profile": {"resolved": resolved},
        "validated_candidate_count": validated,
        "provider_candidate_count": provider,
        "coordinate_candidate_count": provider,
        "evidence_candidate_count": evidence,
        "evidence_candidate_count": evidence,
        "image_candidate_count": images,
        "cross_city_published_count": cross_city_published,
        "mock_published_count": mock_published,
        "elapsed_ms": elapsed_ms,
    }


def test_default_live_suite_covers_five_overseas_destinations():
    assert DEFAULT_CASE_IDS == (
        "live_tromso",
        "live_hobart",
        "live_valletta",
        "live_san_francisco",
        "live_oaxaca",
    )


def test_summary_tracks_safe_degradation_and_publishability_invariants():
    summary = summarize_probe_results(
        [
            _result("live_tromso"),
            _result("live_hobart", status="insufficient_candidates", validated=2),
        ]
    )

    assert summary["resolved_profiles"] == 2
    assert summary["ready_destinations"] == 1
    assert summary["safe_degraded_destinations"] == 1
    assert summary["cross_city_published"] == 0
    assert summary["mock_published"] == 0
    assert summary["coordinate_coverage"] == 1.0


def test_provider_outage_is_not_misreported_as_candidate_shortage():
    summary = summarize_probe_results(
        [_result("live_tromso", status="provider_unavailable", validated=0, provider=0, evidence=0, images=0)]
    )

    assert summary["provider_unavailable_destinations"] == 1
    assert summary["safe_degraded_destinations"] == 0

    result = evaluate_live_acceptance(
        {"results": [_result("live_tromso", status="provider_unavailable", validated=0, provider=0, evidence=0, images=0)]},
        [{"case_id": "live_tromso"}],
    )
    assert result["status"] == "failed"
    assert "provider_availability" in result["failed_checks"]


def test_live_acceptance_allows_one_candidate_shortage_but_rejects_cross_city_publish():
    report = {
        "results": [
            _result("live_tromso"),
            _result("live_hobart"),
            _result("live_valletta"),
            _result("live_san_francisco"),
            _result("live_oaxaca", status="insufficient_candidates", validated=2),
        ]
    }
    cases = [{"case_id": case_id} for case_id in DEFAULT_CASE_IDS]

    accepted = evaluate_live_acceptance(report, cases)
    assert accepted["status"] == "passed"
    assert accepted["failed_checks"] == []

    report["results"][0]["cross_city_published_count"] = 1
    rejected = evaluate_live_acceptance(report, cases)
    assert rejected["status"] == "failed"
    assert "cross_city_published_zero" in rejected["failed_checks"]


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


def test_targeted_probe_accepts_ready_as_upgrade_over_expected_safe_degradation():
    report = {
        "status": "failed",
        "results": [{"case_id": "unseen_oaxaca_insufficient", "status": "ready"}],
    }

    result = apply_targeted_criteria(
        report,
        [
            {
                "case_id": "unseen_oaxaca_insufficient",
                "expected_outcome": "insufficient_candidates",
            }
        ],
    )

    assert result["status"] == "passed"
    assert result["mismatches"] == []
