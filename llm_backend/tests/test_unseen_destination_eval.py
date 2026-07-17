from scripts.unseen_destination_eval import build_report, load_cases, render_markdown


def test_unseen_destination_eval_covers_dynamic_profiles_and_safe_degradation():
    report = build_report(load_cases())

    assert report["status"] == "passed"
    assert report["case_count"] == 10
    assert report["passed_cases"] == 10
    assert report["ready_cases"] == 8
    assert report["insufficient_candidate_cases"] == 2
    assert all(case["profile"]["is_dynamic"] is True for case in report["cases"])
    assert all("outside_destination_radius" in case["reject_reasons"] for case in report["cases"])
    assert "Unseen Destination Grounding Eval" in render_markdown(report)
