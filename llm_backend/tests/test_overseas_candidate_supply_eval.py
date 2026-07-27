from scripts.overseas_candidate_supply_eval import build_report, load_cases, render_markdown


def test_overseas_candidate_supply_eval_closes_three_ready_and_one_safe_degradation():
    report = build_report(load_cases())

    assert report["status"] == "passed"
    assert report["case_count"] == 4
    assert report["passed_cases"] == 4
    assert report["resolved_profiles"] == 4
    assert report["ready_destinations"] == 3
    assert report["safe_degradation_destinations"] == 1
    assert report["cross_city_published"] == 0
    assert report["nearby_cross_city_published"] == 0
    assert report["mock_published"] == 0

    cases = {case["case_id"]: case for case in report["cases"]}
    assert all(
        case["profile"]["source"] == "geoapify_geocode"
        for case in cases.values()
    )
    assert cases["overseas_tromso_ready"]["actual_outcome"] == "ready"
    assert cases["overseas_hobart_ready"]["publishable_candidate_count"] == 3
    assert cases["overseas_valletta_ready"]["actual_outcome"] == "ready"
    assert cases["overseas_oaxaca_insufficient"]["actual_outcome"] == "insufficient_candidates"
    assert cases["overseas_oaxaca_insufficient"]["publishable_candidate_count"] == 2
    assert all(case["mock_published"] == 0 for case in cases.values())
    assert "Overseas Candidate Supply Eval" in render_markdown(report)
