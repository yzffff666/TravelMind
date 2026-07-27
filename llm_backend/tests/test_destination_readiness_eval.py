from scripts.destination_readiness_eval import build_report, load_cases, render_markdown


def test_destination_readiness_eval_covers_static_dynamic_and_safe_degradation():
    report = build_report(load_cases())

    assert report["status"] == "passed"
    assert report["case_count"] == 12
    assert report["passed_cases"] == 12
    assert report["static_cases"] == 6
    assert report["dynamic_cases"] == 6
    assert report["ready_cases"] == 10
    assert report["safe_degradation_cases"] == 2

    cases = {case["case_id"]: case for case in report["cases"]}
    assert cases["static_shenzhen_ready"]["legacy_accepted_count"] == 1
    assert cases["static_shenzhen_ready"]["publishable_candidate_count"] == 3
    assert cases["static_kyoto_ready"]["quality_status"] == "ready"
    assert cases["static_kyoto_ready"]["reject_reason_counts"]["outside_destination_bounds"] >= 1
    assert cases["dynamic_kashgar_safe_degrade"]["actual_outcome"] == "insufficient_candidates"
    assert "Destination Readiness Eval" in render_markdown(report)
