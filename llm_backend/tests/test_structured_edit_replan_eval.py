from scripts.structured_edit_replan_eval import DEFAULT_CASES_PATH, evaluate_cases, is_passing, load_cases


def test_structured_edit_replan_eval_passes_default_cases():
    summary = evaluate_cases(load_cases(DEFAULT_CASES_PATH))

    assert summary["case_count"] >= 15
    assert summary["passed_cases"] == summary["case_count"]
    assert summary["failed_cases"] == 0
    assert summary["unsafe_revision_failures"] == 0
    assert is_passing(summary)
